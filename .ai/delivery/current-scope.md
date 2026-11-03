# Current Delivery Scope

## Active phase

M5 — Side effects, idempotency, and human approval implemented and revision-verifiable.

Accepted scope: D-016 and `docs/superpowers/specs/2026-11-02-m5-side-effects-approval-design.md`. Implementation plan: `docs/superpowers/plans/2026-11-02-m5-side-effects-approval.md`, approved for Native execution.

M5 reuses the three M3 workers as read-only preconditions and adds the first mutating operation: a payload-digest-bound approval gate, a deterministic idempotency key (`cancel-and-refund:ORD-1001`), a scripted file-backed effect ledger with once-per-key enforcement, append-only audit never read back, write-ahead submit markers, and an explicit UNKNOWN terminal when reality cannot be proven. Six paired multi-phase cases cover effect-once, rejection, pre-submit retry, submit-window reconciliation, UNKNOWN, and duplicate-key suppression. The new authority includes ledger/audit parity and the M4→M3→M2→M1→M0 chain. Certification, review, CI, merge and release are separate observed states; inspect candidate evidence rather than inferring success from this scope record.

## Preserved M2 boundary

M2 adds exactly five offline support-handoff cases in TypeScript and Python, a fixed confidence threshold of 0.80, a typed sender-intent/receiver-input boundary, three deterministic receivers, and context-loss/unavailable-receiver rejection without dispatch or retry. Receiver input contains only ticket_id and request_text. M0 and M1 remain regression authorities.

## Next milestone design

The owner accepted [the written M5 side effects and approval design](../../docs/superpowers/specs/2026-11-02-m5-side-effects-approval-design.md), D-016, and the [implementation plan](../../docs/superpowers/plans/2026-11-02-m5-side-effects-approval.md) on 2026-11-02, selecting Native execution. Rulings recorded in the plan ledger: Ruling 4 — order-closure has no synthesis step; the result carries brief null + synthesis_invoked false in every status. The complete authority must be rerun on every changed candidate. No M6 work is included.

## Verification authority

- Local gate: `python scripts/verify_m5.py` (runs M4, which runs M3→M2→M1→M0)
- CI workflow: `.github/workflows/m5.yml`
- Runtime floor: Node.js 24 and Python 3.14
- CI artifact: `m5-verification-<revision>`
- Evidence root: `.boundrelay/m5/`

M5 captures the candidate revision before the regression chain and rechecks clean worktree plus unchanged HEAD before publishing evidence for six cases and all phase traces. It requires lower PASSED proofs on the same revision and passed identities of the independent executor and recovery probes. Generated evidence remains ignored. Run the gate again after any affected change; a status description is not certification evidence.

## Preserved M0 baseline

The gate requires a clean Git worktree and binds its evidence to the checked-out revision. It captures the starting revision, reruns the clean-worktree check immediately before publishing PASSED evidence, and refuses certification if `HEAD` moved during verification. Each passing record includes `scenario_id`, revision, runtime versions, verification command, seven requested case/mode combinations, and fourteen language-specific traces. Any affected implementation, contract, fixture, dependency, test, verifier, or workflow change makes earlier evidence stale and requires a fresh run.

## Completed controls

- canonical route order and support-triage scenario validation;
- exactly one canonical success fixture for each `billing`, `technical`, and `general` route plus one invalid-route failure fixture;
- deterministic baseline and bounded scripted-model decision;
- complete decision-schema validation before dispatch;
- non-finite and oversized Python confidence rejection without unsafe numeric conversion;
- strict JSON event serialization without `NaN` or infinity literals;
- oversized Python integers canonicalized before event storage so traces remain serializable;
- lone-surrogate code points remain writable as escaped JSON during UTF-8 trace output;
- JSONL verification rejects non-standard `NaN`, `Infinity`, and `-Infinity` constants;
- JSONL records are split only on LF, preserving U+0085/U+2028/U+2029 inside JSON strings while still rejecting blank physical records;
- invalid-route fail-closed behavior with no specialist invocation;
- successful runs prove one actual specialist dispatcher invocation for the selected route, while rejection proves zero dispatches;
- all seven canonical scenario/mode executions are exercised with network access denied;
- TypeScript network guards are installed before application module import and proved by an import-time network probe;
- Python network guards are installed before runner import and independently proved in a fresh interpreter;
- schema-valid JSONL events with monotonic sequences;
- exact canonical lifecycle event sequence for deterministic success, model success, and model rejection;
- `run.created`, `run.started`, model events, and classify lifecycle bound to the requested scenario/case/mode;
- `model.completed` decision data bound to the routed outcome;
- classify completion/failure payloads bound to the selected route or failure code;
- exactly one nonblank JSON result line from each verified CLI invocation;
- exact TypeScript CLI option consumption with unknown, positional, and duplicate argument rejection;
- result-to-trace `run_id` binding;
- requested `case_id`, `mode`, and `trace_path` binding;
- exactly one terminal event whose type and payload match the reported result;
- `route.selected`, `route.rejected`, and specialist step payloads bound to the selected route or failure code;
- normalized TypeScript/Python result and trace parity;
- prior evidence removal before the first local gate step;
- starting revision captured before execution and rechecked with a clean worktree immediately before PASSED evidence publication;
- exact PR-head checkout and hidden artifact upload in CI.

## Completed implementation boundary

- support-triage scenario with `billing`, `technical`, and `general` routes;
- TypeScript and Python implementations;
- shared JSON Schema and JSONL event contracts;
- offline scenario execution without API keys;
- one documented local authority;
- revision-bound GitHub Actions evidence;
- no real provider, Go, persistence, UI, MCP, queue, framework adapter, plugin system, or reusable runtime extraction.

## Completion semantics

M0 completion is bounded to the implementation and verification scope defined in `ROADMAP.md`, the foundation design, and the accepted implementation plan. Repository merge and release remain separate governance decisions.
