# M5 Side Effects, Idempotency, and Human Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The owner selected Native execution on 2026-11-02.

**Goal:** Deliver the accepted offline `order-closure` lesson with approval-gated, idempotent effects, append-only audit, an explicit UNKNOWN boundary, and exact-revision evidence across the multi-process authority chain.

**Architecture:** Keep each language implementation lesson-local. Read-only preconditions reuse the M3 workers unchanged; a scripted approval gate binds to the exact payload digest; one idempotent effect submission targets a scripted file-backed ledger; an append-only audit writer records decisions and attempts; UNKNOWN resolution proves reality by key lookup on resume. M4's state store, checkpoints, and bounded executor are reused unchanged beneath M5. Raw trace/state/ledger/audit checks precede semantic projections. One M5 authority owns the M4→M3→M2→M1→M0 regression chain.

**Tech Stack:** Node.js >=24, Python >=3.14, TypeScript strict ESM, Vitest, tsx, Ajv/ajv-formats, PyYAML, jsonschema, unittest, Node `crypto` / Python `hashlib` (digests). Reuse M4's manifest/configuration patterns and pinned versions; no new dependency.

**Spec:** [Accepted M5 design](../specs/2026-11-02-m5-side-effects-approval-design.md), [D-016](../../decisions/D-016-m5-idempotent-approved-effects.md), accepted 2026-11-02.

**Status:** Written design and implementation plan accepted on 2026-11-02. The owner selected Native execution; implementation proceeds on the feature branch. Exact-revision certification, independent review, CI, merge, and release remain separate observed states; consult PR evidence for their current status.

## Global Constraints

- Scenario `order-closure`; canonical input `ORD-1001`; the three M3 workers run unchanged as read-only preconditions with their closed schemas.
- The effect is one deterministic operation, `cancel-and-refund`, keyed `cancel-and-refund:ORD-1001`. The idempotency key is derived in code from operation + order id — never per attempt, never from model output.
- The effect payload is a closed object: `{operation:'cancel-and-refund', order_id, refund_amount_cents: 4200, currency:'EUR'}` with the digest recorded at approval time; the ledger stores `{key, payload_digest, status, outcome}` exactly.
- Approval binds `(operation, order_id, payload_digest)`; a changed digest invalidates approval. No submission without a recorded `granted` approval; rejection ends the run `FAILED` / `APPROVAL_REJECTED` with zero submissions and an audit record.
- The ledger is a scripted lesson-local JSON file with atomic tmp+rename writes and once-per-key enforcement; duplicate submissions adopt the original recorded outcome and mutate nothing.
- The audit writer is append-only (one JSON line per record), never read back by the runtime, and never consulted for recovery decisions.
- The submit→confirm window is the only unsafe window. `crash_in_submit_window` and `sink_unavailable` are fixture controls applied at deterministic boundaries; both phases exit `2` with no result line, and the durable state document is the testimony.
- Resume after a submit-window crash queries the ledger by key: present → adopt the original outcome, complete `SUCCEEDED` with `reconciled: true`, never re-submit; absent → re-submit under the same key; lookup unavailable → terminate `UNKNOWN` (result line, exit `0`, state doc `UNKNOWN`), never flattened.
- Run status set gains `UNKNOWN`; result schema gains `reconciled` (boolean) and `approval_decision` (`granted|rejected|none`); `failure_code` gains `APPROVAL_REJECTED`. All M4 result fields stay.
- Event envelope stays `1.0`; the type enum gains exactly the foundation-declared `approval.requested`, `approval.granted`, `approval.rejected`, `tool.requested`, `tool.completed`, `tool.failed`. Payloads carry safe identifiers, digests, and the key — never raw payloads or ledger contents.
- Exactly six canonical cases; per-phase exit-code/stdout assertions as M4; exactly one nonblank JSON result line per completed phase.
- Stay offline and framework-free. Exclude real networks/services, approval services, outboxes/queues, locks, model-driven effects, timeouts/forced termination, Go, MCP, framework mappings, and shared-runtime extraction.
- Publish evidence only on a clean unchanged candidate revision, after M4 (and its lower chain) pass on that same revision. Safety checks must survive `python -O`.

## Review Focus

| Failure/input class | Required evidence | Owner |
|---|---|---|
| Submission without a granted approval bound to the exact digest | Approval-binding tests; zero submissions on rejection | Tasks 2–3 |
| A second ledger record for one key, or a re-submitted landed effect | Once-per-key tests + resume reconciliation probes | Tasks 2, 4 |
| UNKNOWN flattened to SUCCEEDED/FAILED, or resolved without proof | sink-unavailable probe; state/result/terminal UNKNOWN agreement | Tasks 4–5 |
| Audit reordered, rewritten, or read back for decisions | Append-only assertion + runtime-never-reads-audit probe | Tasks 2, 6 |
| Parity projection hides approval/tool/checkpoint behavior or ledger drift | Raw-first mutation suite incl. digest and key bindings | Task 6 |
| Certification without real subprocess durability proof | Multi-phase case records with per-phase exit codes | Tasks 6–7 |

## File and Interface Map

Use `TS = lessons/05-side-effects-approval/typescript` and `PY = lessons/05-side-effects-approval/python`. All paths below are repository-relative; braces enumerate exact files. Python module prefix is `boundrelay_m5`.

| Files | Responsibility |
|---|---|
| `contracts/effects/order-closure-effect.schema.json`, `contracts/results/order-closure-result.schema.json`, `contracts/audit/order-closure-audit.schema.json` | Closed effect payload/outcome, result (incl. UNKNOWN + reconciliation fields), audit schemas |
| `fixtures/scenarios/order-closure.yaml` (+ approval/sink controls) | Six cases, approval decisions, crash windows |
| `TS/src/{types,paths,schemas,scenario,workers,scripted-workers,state-store,idempotency,effect-ledger,approval,audit}.ts`; `PY/src/boundrelay_m5/` mirrors | Types, key derivation, ledger, approval binding, audit |
| `TS/src/executor.ts` (M4 reuse + effect step); Python mirror | Bounded reads + one gated effect step |
| `TS/src/{recovery,trace,runner,cli}.ts`; Python equivalents and `__main__.py` | UNKNOWN resolution, event lifecycle, orchestration, CLI |
| `tools/parity/{verify_m5,test_m5_verification_safety}.py`, `scripts/verify_m5.py` | Raw checks, multi-phase parity, gate, proof publication |
| `lessons/05-side-effects-approval/{README.md,invariants.yaml}`, `.github/workflows/m5.yml` | Teaching, invariant map, exact-head CI |

### Stable Interfaces

Define these in Task 2; subsequent tasks consume the same names and wire fields. Python uses snake_case; wire fields are snake_case in both languages.

- `EffectPayload`: exactly `{operation:'cancel-and-refund', order_id, refund_amount_cents:4200, currency:'EUR'}`. `effectDigest(payload): string` / `effect_digest(...)` (SHA-256 over canonical JSON). `effectKey(payload): string` / `effect_key(...)` = `cancel-and-refund:ORD-1001` style derivation.
- `EffectLedger`: `submit(payload, digest?): {status:'EFFECT_COMPLETED'|'EFFECT_REJECTED', outcome, duplicate:false}` or `{status, outcome, duplicate:true}` adopting the original; `lookup(key): {status, outcome}|null`; `records(): array`; atomic writes; once-per-key. Python snake_case mirrors.
- `ApprovalRecord`: `{operation, order_id, payload_digest, decision:'granted'|'rejected', approver}`; `ApprovalGate.decide(payload_digest): 'granted'|'rejected'` from validated fixture metadata; binding check `requireApproval(record, payload)` raises on digest/operation/order mismatch.
- `AuditWriter`: `append(record)` with a closed audit schema; append-only file semantics (no rewrite); `records(): read-only view` for tests only.
- `RecoveryControls` gains `crash_in_submit_window?: boolean` and `sink_unavailable?: boolean` (fixture-validated, at most one per case).
- `ExecutorOptions` unchanged from M4 for reads; the effect step is a separate bounded step owned by the runner: reads (bounded executor) → approval → submit.
- `RunOptions`: M4's shape plus `sink?: EffectSink` (event sink) and effect-step wiring; `runCase(options)` owns the full pipeline and UNKNOWN resolution.
- `TraceSink` as M4; the lesson-local event context gains the six new foundation-declared event types.

### Canonical Cases

All cases use parallel-mode precondition reads and the fixed payload; controls are validated by the fixture grammar.

| Case | Phases | Injected difference | Outcome |
|---|---|---|---|
| `approval-granted-effect-once` | 1 run | none | granted → one submission → `SUCCEEDED`, one ledger record |
| `approval-rejected-no-effect` | 1 run | scripted rejection | `FAILED`/`APPROVAL_REJECTED`, zero submissions |
| `retry-before-submit` | crash + resume | crash before submission | resume submits once → `SUCCEEDED` |
| `crash-submit-window-resolved` | crash + resume | crash between submit and confirm | resume finds the key → adopts outcome → `SUCCEEDED`, `reconciled:true` |
| `sink-unavailable-unknown` | crash + resume | lookup unavailable | `UNKNOWN` terminal, never flattened |
| `duplicate-key-suppressed` | run + second run | same key | second run adopts recorded outcome, ledger unchanged |

## Commands and Working Directory

Use repository root as explicit cwd. On this Windows host use `.venv/Scripts/python.exe` for `python` and `npm.cmd` for `npm`. Set `$env:PYTHONPATH='lessons/05-side-effects-approval/python/src'` before Python unit commands. A RED step must fail on its named behavioral assertion, not missing packages. After each task's GREEN steps, run its affected tests and TS typecheck, stage only its files, and commit with the specified message. Run the complete clean-revision authority after Task 7; intermediate checks do not certify M5.

## Task 1: Shared Contracts, Fixtures, and Invariant Catalog

**Files — Create:** `contracts/effects/order-closure-effect.schema.json`, `contracts/results/order-closure-result.schema.json`, `contracts/audit/order-closure-audit.schema.json`, `fixtures/scenarios/order-closure.yaml`, `tools/contracts/test_m5_contracts.py`, `lessons/05-side-effects-approval/invariants.yaml`.

**Interfaces:** Result schema extends M4's (status +UNKNOWN, +`reconciled`, +`approval_decision`, failure_code +`APPROVAL_REJECTED`, scenario_id `order-closure`). Effect schema: closed payload + outcome. Audit schema: closed records. Scenario YAML: `{schema_version, scenario_id, order_id, cases}` with case fields `{case_id, execution_mode, worker_fixture, completion_order, approval, controls?, tamper?}`; `approval: {decision:'granted'|'rejected', approver}`; controls at most one of `crash_in_submit_window|sink_unavailable` or a phase marker `crash_before_submit`. No new worker grammar; M3 worker fixtures reused.

- [ ] Write `test_six_cases_and_closed_effect_contract` + `test_result_status_count_policy` with: six unique cases; closed effect schema rejects extra fields/wrong enums/wrong order id; result schema rejects UNKNOWN with failure_code, reconciled-on-clean-run, approval_decision 'granted' with zero submissions; audit schema rejects rewrite-shaped records. Helpers via Draft202012Validator on real schema files.
- [ ] Run `python -m unittest tools.contracts.test_m5_contracts -v`; expect RED on missing contracts/fixtures.
- [ ] Implement closed schemas, exact six cases, and the twenty-entry invariant catalog `M5-01`–`M5-20` mapped to spec sections 5–6.
- [ ] Rerun the contract command; expect PASS.
- [ ] Commit only Task 1 files: `feat: define M5 effect contracts and closure fixtures`.

## Task 2: Foundations: Idempotency, Ledger, Approval, Audit

**Files — Create:** `TS/{src/types.ts,src/paths.ts,src/schemas.ts,src/scenario.ts,src/workers.ts,src/scripted-workers.ts,src/state-store.ts,src/idempotency.ts,src/effect-ledger.ts,src/approval.ts,src/audit.ts}` + manifests; `TS/test/{foundations,effect-ledger,approval,audit,scenario,schemas,scripted-workers,state-store}.test.ts`; `PY/src/boundrelay_m5/` mirrors; `PY/tests/test_*.py` mirrors.

**Interfaces:** Produce the Stable Interfaces (types/validation/digest/key/ledger/approval/audit/store/scenario). `loadScenario` validates approval blocks, at-most-one control, feasible crash boundaries (crash_before_submit must precede any submission; crash_in_submit_window must sit exactly in the submit→confirm gap), and M3 worker fixture reuse.

- [ ] Scaffold manifests from M4 (names `@boundrelay/lesson-05-typescript` / `boundrelay-m5`), install, commit lockfile.
- [ ] Paired `effect_key_is_deterministic_and_stable`: same payload → same key/digest; different order id → different key; key never from model output.
- [ ] Paired `ledger_enforces_once_per_key`: first submit records; duplicate adopts original outcome (`duplicate:true`), ledger unchanged; invalid payload → `EFFECT_REJECTED` outcome recorded once; atomicity under interrupted write leaves previous ledger loadable.
- [ ] Paired `approval_binds_to_payload_digest`: granted approval for digest A rejects payload B; rejected decision is terminal; approval record requires exact operation/order/digest.
- [ ] Paired `audit_is_append_only_and_never_read`: two appends keep order; no rewrite API; runtime recovery path never opens the audit file (assert via injected writer spy).
- [ ] Paired state-store/scenario tests mirror M4's with M5 bindings.
- [ ] RED → implement → GREEN → typecheck clean.
- [ ] Commit only Task 2 files: `feat: add M5 idempotency ledger and approval foundations`.

## Task 3: Approval-Gated Effect Pipeline with Submit Markers

**Files — Create:** `TS/src/executor.ts` (M4 executor reuse + effect step), `TS/test/executor.test.ts`; `PY/src/boundrelay_m5/executor.py`, `PY/tests/test_executor.py`.

**Interfaces:** The runner owns the pipeline: bounded reads (M4 executor, no controls) → approval gate → effect submission. The executor gains an `effectStep` hook: `{submit(payload): {status,outcome,duplicate}}` invoked once after reads and approval; a store `markSubmitted(key)` checkpoint before `submit()` returns... ORDER: markSubmitted checkpoint (submit-marker) is written BEFORE the ledger submit is called; the ledger outcome is recorded through the store after it returns. `crash_in_submit_window` fires after the ledger accepted the submission but before the store records the confirmation.

- [ ] Paired `no_submission_without_granted_approval`: rejected/absent approval → zero submit() calls, FAILED/APPROVAL_REJECTED, audit records the rejection.
- [ ] Paired `submit_marker_precedes_ledger_submit_and_outcome_recorded_after`: with instrumented ledger/store, assert write-ahead order: marker checkpoint → ledger.submit() → store outcome record → audit line; crash_in_submit_window fires between submit() and store-record, verified by an on_crash spy called exactly once.
- [ ] Paired reads/effect probes: reads run once each (bounded), effect submitted exactly once with the deterministic key, payload digest matches approval binding.
- [ ] RED → implement → GREEN → typecheck clean.
- [ ] Commit only Task 3 files: `feat: gate M5 effect behind approval and submit markers`.

## Task 4: UNKNOWN Resolution on Recovery

**Files — Create:** `TS/src/recovery.ts`, `TS/test/recovery.test.ts`; `PY/src/boundrelay_m5/recovery.py`, `PY/tests/test_recovery.py`.

**Interfaces:** Consume M4's loadRunState/StateStore.resume + M5's ledger lookup. Resume behaviors: state has submit-marker without recorded outcome → query ledger by key → present: adopt outcome (`reconciled:true`, no submit), absent: submit once (same key), lookup unavailable (control): complete `UNKNOWN` — result line, exit 0, state doc `UNKNOWN`, no flattening. `duplicate-key-suppressed` recovery: a run resumed after full success re-adopts without submission.

- [ ] Paired `resume_proves_landed_effect_by_key_lookup`: submit-marker present + ledger has the key → adopt, `reconciled:true`, ledger still one record, zero submit() calls.
- [ ] Paired `resume_resubmits_absent_effect_under_same_key`: marker present + key absent → submit once → SUCCEEDED, `reconciled:false`.
- [ ] Paired `unprovable_effect_stays_unknown`: marker present + sink_unavailable control → UNKNOWN result (line, exit 0 semantics at CLI level in Task 5), state doc UNKNOWN, no flattening, no submit.
- [ ] Paired `duplicate_key_adopts_recorded_outcome`: fresh run against an already-keyed ledger → duplicate:true adoption → SUCCEEDED, ledger unchanged.
- [ ] RED → implement → GREEN → typecheck clean.
- [ ] Commit only Task 4 files: `feat: resolve M5 unprovable effects through key lookup`.

## Task 5: Runner, CLI, Trace Events, and Offline Guards

**Files — Create:** `TS/src/{trace,runner,cli}.ts`, `TS/test/{runner,cli,offline,multiphase}.test.ts`; `PY/src/boundrelay_m5/{trace,runner,cli,__main__}.py`, `PY/tests/test_{runner,cli_trace,offline}.py`, `PY/tests/offline_runner.py`.

**Interfaces:** `runCase` full lifecycle: run.created/started → reads (step.* events, M4 payloads) → approval.requested → approval.granted|rejected → tool.requested (effect, side-effect class) → tool.completed|tool.failed + checkpoint markers → terminal event. Approval rejection: FAILED/APPROVAL_REJECTED result. UNKNOWN: result line + state doc UNKNOWN, no terminal flattening (terminal event carries the UNKNOWN status). Event enum gains exactly the six foundation-declared types. CLI grammar: `--case <id> --trace <path> --state-dir <dir> [--resume]` (replay not in M5 canonical scope; keep M4's --replay-from out unless the design requires it — it does not).

- [ ] Paired `approval_and_tool_events_bound_to_payload_digest`: approval events carry operation/order/digest; tool events carry the key + declared side-effect class; no raw payload values.
- [ ] Paired `rejected_run_has_zero_submissions_and_audit_record`: result FAILED/APPROVAL_REJECTED, exit 0, ledger empty, audit has the rejection.
- [ ] Paired `unknown_run_emits_result_line_and_unknown_state`: CLI subprocess (or unit) run with sink_unavailable → stdout JSON with status UNKNOWN, run_state_status UNKNOWN, exit 0.
- [ ] Paired multi-phase subprocess tests: retry-before-submit (crash exit 2 → resume SUCCEEDED), crash-submit-window-resolved (crash exit 2 → resume SUCCEEDED reconciled:true), duplicate-key-suppressed (two runs → one ledger record).
- [ ] Offline guards: M2/M3/M4 pattern (fresh-process network probes, guards before runner import).
- [ ] RED → implement → GREEN → typecheck clean.
- [ ] Commit only Task 5 files: `feat: expose M5 offline runs and effect trace lifecycle`.

## Task 6: Raw-First Parity and Exact-Revision Verification Authority

**Files — Create:** `tools/parity/verify_m5.py`, `tools/parity/test_m5_verification_safety.py`, `scripts/verify_m5.py`.

**Interfaces:** Mirror M4's gate structure: clear `.boundrelay/m5` → clean-worktree + starting SHA → invoke `scripts/verify_m4.py` once → validate M4 evidence SHA+PASSED → contracts, TS typecheck+vitest JSON report, PY ProofResult suite, safety suite normal + `-O`, six paired case flows with per-phase exit/stdout assertions → raw-first validation (per-phase JSONL, approval-before-submission ordering, one tool.requested per attempt, audit-line ordering, ledger once-per-key, state/result/terminal agreement incl. UNKNOWN) → normalized ledger/audit/state comparisons across languages → business projections (effect-once set: clean vs retry-before-submit vs crash-window-resolved) → recheck clean HEAD → publish `.boundrelay/m5/verification-evidence.json`.

- [ ] `test_raw_mutations_fail_before_projection`: submission without approval, second ledger record per key, UNKNOWN flattened, stale-digest approval, audit rewritten/reordered, re-submitted landed effect, missing checkpoint marker, wrong binding, NaN/blank JSONL, duplicate terminal → each raises before projection.
- [ ] `test_missing_probe_or_zero_suite_cannot_certify` + `test_publication_checks_survive_optimization` (M4 patterns, exact probe identities from the executor/recovery suites).
- [ ] RED → implement → GREEN; run all six case flows manually; full authority deferred to Task 7.
- [ ] Commit only Task 6 files: `test: certify M5 effect parity and audit evidence`.

## Task 7: Teaching Demonstration, CI, and Candidate Certification

**Files — Create:** `lessons/05-side-effects-approval/README.md`, `.github/workflows/m5.yml`, `TS/test/naive-example.test.ts`, `PY/tests/test_naive_example.py`. **Modify:** root `README.md`, `.ai/delivery/current-scope.md`.

**Interfaces:** Test-local naive example only. CI runs `python scripts/verify_m5.py` on the exact candidate SHA (Node 24 / Python 3.14), uploads `m5-verification-<revision>` with hidden files. M4 remains the implemented authority until the new authority passes.

- [ ] Paired `naive_retry_refires_the_effect`: after a submit-window crash, naive retry submits again (ledger would record two keys or a duplicate attempt at the runtime layer) while the corrected resume proves-by-lookup and submits zero times; instrumented ledger proves the contrast. No sleep, no external call, no seventh case.
- [ ] RED → implement the demonstration inside test modules only → GREEN.
- [ ] Lesson README: read-only preconditions → approval gate → idempotent effect → audit → UNKNOWN boundary → reconciliation. Include exact multi-phase CLI commands, ledger/audit examples, the exit-code table, approval-binding rationale, invariants, and evidence limits. Explain when full re-submission is never acceptable; no production-safety claims beyond the evidence.
- [ ] Exact-head M5 workflow (current action versions, `persist-credentials:false`, PR/main triggers, hidden evidence upload). Update root README and scope to point to the M5 authority with precise implementation status.
- [ ] Inspect scope/diff, `git diff --check`, commit Task 7 files: `docs: teach M5 effects and enable revision bound CI`. Do not change M0–M4 domain code or the global normalizer.
- [ ] On the clean committed candidate run `python scripts/verify_m5.py`; expect PASSED on the exact SHA with lower chain PASSED, six case records, all phase traces, and required probe identities. Rerun after any fix, on the new clean revision.
- [ ] Fresh whole-branch review; resolve material findings in scope; rerun affected checks + full authority when evidence is invalidated.
- [ ] Push/update the PR; check M0–M5 CI on the exact head; verify the downloaded M5 artifact. Merge/release require the owner's separate authorization.
- [ ] Append the activity entry and update continuation state with actual SHA, PR/CI/evidence status, blockers, and the next bounded action.

## Inline Self-Review and Coverage

Reviewed this plan against all spec sections. Tasks 1–2 fix effect/approval/ledger/audit contracts and key derivation; Task 3 owns the approval gate and write-ahead submit markers; Task 4 owns UNKNOWN resolution and key-lookup reconciliation; Task 5 owns publication, events, CLI, and offline guards; Task 6 owns raw validation, ledger/audit parity, and evidence; Task 7 owns the D-005 teaching sequence, CI, and completion. No M5 product code is included in this planning change.

| Spec areas | Implementation and evidence |
|---|---|
| Approval binding + rejection | Tasks 2–3, 5 (digest binding, zero submissions, audit record) |
| Idempotency + safe windows | Tasks 2–4 (once-per-key, submit markers, key-lookup reconciliation) |
| UNKNOWN boundary | Tasks 4–6 (never flattened, state/result/terminal agreement) |
| Audit append-only | Tasks 2, 6 (append-only writer, never-read probe) |
| M4 substrate unchanged | Tasks 3–5 (store/checkpoints/executor reuse; M4 invariants hold) |

All six Review Focus rows have named tests. The plan specifies signatures and behavioral assertions rather than implementation bodies. Crash/sink controls are scripted fixture boundaries, not runtime infrastructure. Future-file paths above are planned artifacts, not claims they already exist.

## Execution Handoff

The owner approved this written plan and selected **Native** on 2026-11-02: implement the seven tasks in this session using `superpowers:executing-plans`, then obtain one fresh whole-branch review. Keep implementation within the accepted design and record any necessary ruling in the plan's execution ledger.

## Execution Ledger

| Date | Task | Ruling | Effect |
|---|---|---|---|
| 2026-11-02 | Task 3 | Ruling 4: `order-closure` has no synthesis step. | The M5 result schema pins `synthesis_invoked` to `false` and `brief` to `null` in every status branch (SUCCEEDED/PARTIAL/FAILED+ALL_WORKERS_FAILED/FAILED+APPROVAL_REJECTED/CANCELLED/UNKNOWN). Result builders and downstream consumers treat the M4 brief/synthesis fields as vestigial; no brief is ever produced. |





