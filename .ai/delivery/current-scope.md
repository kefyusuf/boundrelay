# Current Delivery Scope

## Active phase

M3 — Bounded read-only fan-out/fan-in implemented; candidate qualification in progress.

Accepted scope: D-014 and `docs/superpowers/specs/2026-10-05-m3-bounded-fanout-fanin-design.md`. Implementation plan: `docs/superpowers/plans/2026-10-05-m3-bounded-fanout-fanin.md`, approved for Native execution.

M3 fixes three independent order-brief workers, sequential cap1 / parallel cap2, once-only invocation, explicit partial/all-failed outcomes, complete canonical fan-in, one deterministic synthesis owner and six offline paired cases. The new authority includes independent worker-body proof, raw-first trace validation and the M2→M1→M0 chain. Certification, review, CI, merge and release are separate observed states; inspect candidate evidence rather than inferring success from this scope record.

## Preserved M2 boundary

M2 adds exactly five offline support-handoff cases in TypeScript and Python, a fixed confidence threshold of 0.80, a typed sender-intent/receiver-input boundary, three deterministic receivers, and context-loss/unavailable-receiver rejection without dispatch or retry. Receiver input contains only ticket_id and request_text. M0 and M1 remain regression authorities.

## Next milestone design

The owner accepted [the written M3 fan-out/fan-in design](../../docs/superpowers/specs/2026-10-05-m3-bounded-fanout-fanin-design.md), D-014, and the [implementation plan](../../docs/superpowers/plans/2026-10-05-m3-bounded-fanout-fanin.md) on 2026-10-05, selecting Native execution. The implementation now awaits complete current-revision qualification and whole-branch review. No M4/M5 work is included.

## Verification authority

- Local gate: `python scripts/verify_m3.py` (runs M2, which runs M1/M0)
- CI workflow: `.github/workflows/m3.yml`
- Runtime floor: Node.js 24 and Python 3.14
- CI artifact: `m3-verification-<revision>`
- Evidence root: `.boundrelay/m3/`

M3 captures the candidate revision before the regression chain and rechecks clean worktree plus unchanged HEAD before publishing evidence for six cases and twelve language-specific traces. It requires lower PASSED proofs on the same revision and passed identities of all four independent executor probes. Generated evidence remains ignored. Run the gate again after any affected change; a status description is not certification evidence.

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
