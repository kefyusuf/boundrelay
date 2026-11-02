# M5 Side Effects, Idempotency, and Human Approval Design

- **Date:** 2026-11-02
- **Status:** Accepted by the owner on 2026-11-02; implementation planning follows
- **Milestone:** M5 — Side effects, idempotency, and human approval
- **Project:** BoundRelay
- **Baseline:** merged M4 at `dc27e8a1684f93094c064f63b5e0b67c86eb3102`
- **Decision:** [D-016](../../decisions/D-016-m5-idempotent-approved-effects.md), proposed
- **Depends on:** [foundation design](../../design/2026-09-02-foundation-design.md), D-001 through D-015, completed M0–M4 verification

## 1. Purpose and design brief

M5 teaches the first milestone where an operation can change external reality. The roadmap requires idempotency keys, safe retry boundaries, approval before irreversible action, audit records, and an explicit `UNKNOWN` outcome when external reality cannot be proven.

This proposed design preserves offline execution, TypeScript/Python parity, lesson-local implementations, shared behavioral contracts, and exact-revision evidence. The "external effect" is a scripted, file-backed effect ledger inside the lesson — deterministic, inspectable, and free of real networks or services. M4's durable state and checkpoints are reused unchanged; M5 adds what side effects demand on top of them.

The teaching objective is:

> A side effect divides every retry into safe and unsafe halves. Approval must gate the irreversible half. An effect whose outcome cannot be proven stays UNKNOWN — it is never flattened into success or failure — and an idempotency key is how later runs prove what actually happened.

## 2. Approaches considered

| Approach | Benefit | Limit | Choice |
|---|---|---|---|
| Scripted file-backed effect ledger with idempotency keys, approval gate, and UNKNOWN resolution | Isolates effect-once semantics, approval, audit, and UNKNOWN deterministically; reuses M4 durability | Does not teach real network semantics, provider retries, or transactional outboxes | Recommended |
| Read-only milestone; defer all effects to a later phase | Smallest step | Postpones the roadmap's M5 scope indefinitely; M4 already proved the durability substrate | Rejected |
| Real HTTP/file side effects against a sandbox | Realism | Nondeterministic evidence, network dependency, violates D-006 | Rejected |

### Teaching sequence

Follow D-005: establish what breaks when a retry re-fires an effect (duplicate refunds), show the naive double-submission, inject approval rejection and crash windows, correct with an approval gate + idempotency ledger + UNKNOWN semantics, and prove the invariants. The lesson explains why approval must bind to the exact requested effect and why the submit→confirm window is the only dangerous window.

## 3. Canonical scenario: order closure

The scenario ID is `order-closure`. Input: known order identifier `ORD-1001`. The operation requests cancelling the order and issuing one refund — the first mutating business action in the project.

The pipeline has four bounded steps:

1. **Precondition reads** — the three M3 workers (`order-details`, `payment-status`, `delivery-status`) run unchanged as read-only checks; the canonical records are order `SHIPPED`, payment `PAID`, delivery `DELAYED`. Precondition failure (any read failing or an unsupported combination) fails the run before any approval or effect; retrying reads is always safe.
2. **Approval gate** — one scripted approval decision for `(operation=cancel-and-refund, order_id, effect payload digest)`. The request records what will happen; the decision is `granted` or `rejected`. A changed request (different digest) invalidates a prior approval. Rejection ends the run `FAILED` / `APPROVAL_REJECTED` with zero effect submissions.
3. **One idempotent effect** — a single submission to the scripted effect sink: `cancel-and-refund` keyed by the deterministic idempotency key `cancel-and-refund:ORD-1001`. The sink is a lesson-local JSON ledger (atomic writes, M4 store patterns) mapping keys to recorded attempt outcomes. The sink validates the payload against a closed schema and records exactly one outcome per key.
4. **Audit record** — an append-only audit line per attempt and per approval decision, written under the state directory. Audit is history, not recovery authority: the runtime never reads audit back to decide anything.

The M4 run-state document, checkpoints, resume, and cancellation rules apply unchanged. Approval decisions and the submit marker are checkpointed, shrinking the unprovable window to exactly the submit→confirm gap.

## 4. Idempotency keys and safe retry boundaries

The idempotency key is derived deterministically from the operation and inputs — never generated per attempt, never accepted from a model response. Every submission carries the key; the sink enforces once-per-key: a duplicate submission returns the original recorded outcome and performs no new mutation.

Retry boundaries are explicit:

| Window | Retry safety | Mechanism |
|---|---|---|
| Before submission (reads, approval request) | Always safe — pure reads and recorded decisions | ordinary resume/retry |
| Submit → confirm | **Unsafe** — the effect may or may not have landed | idempotency key + UNKNOWN until proven |
| After confirmation | Safe — duplicate submissions are suppressed | key lookup returns the recorded outcome |

## 5. UNKNOWN: explicit unprovability

A scripted crash control can fire inside the submit→confirm window: the submission reached the sink but the run died before recording the confirmation. The recovered run queries the sink by idempotency key:

- **Key present:** reality is proven — the original outcome is adopted, the run completes `SUCCEEDED` with `reconciled: true`. No second mutation occurs.
- **Key absent:** no effect landed — the run may re-submit (the key still guards duplicates) and complete normally.
- **Sink lookup itself unavailable** (scripted control): the run terminates `UNKNOWN` — a domain outcome with a result line and exit `0`, whose state document keeps `status: UNKNOWN`. `UNKNOWN` is never flattened into `SUCCEEDED` or `FAILED`, and no retry logic silently resolves it.

`UNKNOWN` extends the run status set (`RUNNING|SUCCEEDED|PARTIAL|FAILED|CANCELLED|UNKNOWN`) and the state document's terminal statuses. The foundation's state machine already declares it; M5 is the first milestone that can reach it.

## 6. Approval boundary

Approval is requested before the first submission and recorded (checkpointed) once granted. The approval record binds: operation, order id, effect payload digest, decision, and a deterministic approver identity from the fixture. Rules:

- No submission without a recorded `granted` approval bound to the exact payload digest.
- A rejected decision is terminal for that run: `FAILED` / `APPROVAL_REJECTED`, zero submissions, resumable only to re-request approval after a changed request (new digest).
- Approval events use the foundation's `approval.requested`, `approval.granted`, `approval.rejected` event types; payloads carry safe identifiers and the digest only.

## 7. Effect sink boundary

The sink is a scripted lesson-local component: a JSON ledger file (atomic tmp+rename writes), keyed by idempotency key, each record containing the key, payload digest, status, and outcome. It validates submissions against a closed schema, rejects unknown shapes, and never executes anything external. Crash and lookup-unavailability are fixture controls (`crash_in_submit_window`, `sink_unavailable`) — deterministic, test-only, never runtime infrastructure.

The sink records the effect attempt outcome in exactly three classes: `EFFECT_COMPLETED` (with the typed refund result), `EFFECT_REJECTED` (invalid payload), and — through the crash control — no record at all (the unprovable case).

## 8. Canonical cases

Exactly six paired cases, all parallel-mode preconditions and one effect step:

| Case | Phases | Injected difference | Outcome |
|---|---|---|---|
| `approval-granted-effect-once` | 1 run | none | approval granted → one submission → `SUCCEEDED`, ledger has one record |
| `approval-rejected-no-effect` | 1 run | scripted rejection | `FAILED` / `APPROVAL_REJECTED`, zero submissions, audit records the rejection |
| `retry-before-submit` | crash + resume | crash before submission | resume submits once → `SUCCEEDED` |
| `crash-submit-window-resolved` | crash + resume | crash between submit and confirm | `UNKNOWN` terminal in phase 1? no — resume finds the key in the ledger → adopts original outcome → `SUCCEEDED`, `reconciled: true` |
| `sink-unavailable-unknown` | run + resume | sink lookup unavailable after submit-window crash | run terminates `UNKNOWN` (result line, exit `0`), never flattened; state doc `UNKNOWN` |
| `duplicate-key-suppressed` | run + second run | same key, second run | second run adopts the recorded outcome, ledger still has one record |

The crash controls reuse M4's quiescent-boundary discipline: boundaries are timing-independent and validated by the fixture grammar. Extra unit tests cover changed-payload approval invalidation, invalid effect payload rejection, audit append-only behavior, and key-derivation stability; they are not canonical cases.

## 9. Result and trace contract

The result schema extends M4's: `status` gains `UNKNOWN`; `reconciled` (boolean) and `approval_decision` (`granted|rejected|none`) join the recovery fields; `failure_code` gains `APPROVAL_REJECTED`. `UNKNOWN` results carry the idempotency key and the reason code `EFFECT_UNPROVABLE`.

The event envelope stays at version `1.0`. The type enum gains only foundation-declared members used for the first time: `approval.requested`, `approval.granted`, `approval.rejected`, plus tool events for the effect step (`tool.requested`, `tool.completed`, `tool.failed`) with the effect's declared side-effect class. Payloads carry safe identifiers, digests, and the idempotency key — never raw payloads or ledger contents.

## 10. Validation, normalization, and parity

Raw-first validation extends M4's: per-phase strict JSONL, one terminal per completed phase, approval-before-submission ordering, exactly one `tool.requested` per run attempt, audit-line ordering, ledger once-per-key, and state/result/terminal agreement. Mutation tests must reject: submission without granted approval, a second ledger record for one key, `UNKNOWN` flattened to `SUCCEEDED`/`FAILED`, an approval bound to a stale digest, audit reordered or rewritten, or a reconciled run that re-submitted.

Same-case language parity covers normalized results, event lifecycles, ledger contents (normalized), and audit sequences. Business projections compare `approval-granted-effect-once` vs `retry-before-submit` vs `crash-submit-window-resolved` (all `SUCCEEDED`, one ledger record) and prove the `UNKNOWN` case stands alone.

## 11. Verification authority and evidence

The documented authority is `python scripts/verify_m5.py`, capturing a clean starting revision and invoking `python scripts/verify_m4.py` once (the M4→M0 chain). The gate runs contracts, both language suites, offline guards, verifier-safety mutation tests (normal and `python -O`), all six paired case flows with per-phase exit assertions, ledger/audit/normalized-state comparisons, and business projections. Evidence publishes to `.boundrelay/m5/verification-evidence.json` only on a clean unchanged HEAD; CI uploads `m5-verification-<revision>`.

## 12. Planned artifacts and architecture

- `lessons/05-side-effects-approval/{typescript,python}/`: precondition reads (M3 workers), approval gate, idempotency key derivation, scripted effect ledger, audit writer, UNKNOWN resolution, runner, CLI, and tests;
- `lessons/05-side-effects-approval/{README.md,invariants.yaml}` (twenty invariants `M5-01`–`M5-20`);
- `contracts/effects/order-closure-effect.schema.json` (closed effect payload + outcome), `contracts/results/order-closure-result.schema.json`, `contracts/audit/order-closure-audit.schema.json`;
- `fixtures/scenarios/order-closure.yaml` (+ approval and sink-control fixtures);
- `tools/contracts/test_m5_contracts.py`, `tools/parity/{verify_m5,test_m5_verification_safety}.py`, `scripts/verify_m5.py`, `.github/workflows/m5.yml`.

No new dependencies. The event-type enum gains only foundation-declared members.

## 13. Invariants and completion criteria

1. No effect submission without a recorded granted approval bound to the exact payload digest.
2. The idempotency key is deterministic, stable across attempts, and never accepted from model output.
3. The ledger records at most one outcome per key; duplicates adopt the original outcome.
4. Retries before submission are free; the submit→confirm window is the only unsafe window.
5. An unprovable effect keeps the run `UNKNOWN` — never flattened.
6. Resume after a submit-window crash proves reality by key lookup and never re-submits a landed effect.
7. Rejection produces zero submissions and an audit record.
8. Audit is append-only and never consulted for recovery decisions.
9. Approval and submit markers are checkpointed before the effect step.
10. All M4 durability invariants hold unchanged beneath M5.

… (invariants 11–20 completed at plan time; the design catalog is finalized in the implementation plan.)

## 14. Explicit exclusions

M5 does not introduce real networks, real payment/refund services, transactional outboxes or real message queues, distributed locks, model-driven decisions, approval UIs or humans-in-the-loop services, timeouts/forced termination, Go, MCP, framework mappings, or shared-runtime extraction. The approval "approver" is a scripted fixture decision, not a human service. These remain later decisions.

## 15. Written-design review gate

The owner approved this written design and D-016 on 2026-11-02, covering the order-closure scenario, approval binding, idempotency-key semantics, the UNKNOWN boundary, the scripted ledger, the six canonical cases, and the revision-bound authority.

The implementation plan is the next review artifact. Review that plan and select its execution method before product implementation. Design acceptance alone does not authorize product code, schema, fixture, dependency, or workflow implementation.

