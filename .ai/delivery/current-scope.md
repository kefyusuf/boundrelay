# Current Delivery Scope

## Active phase

M0 — Behavioral parity vertical slice complete and revision-verifiable.

## Verification authority

- Local gate: `python scripts/verify_m0.py`
- CI workflow: `.github/workflows/m0.yml`
- Runtime floor: Node.js 24 and Python 3.14
- CI artifact: `m0-verification-<revision>`
- Evidence root: `.boundrelay/m0/`

The gate requires a clean Git worktree and binds its evidence to the checked-out revision. Each passing record includes `scenario_id`, revision, runtime versions, verification command, seven requested case/mode combinations, and fourteen language-specific traces. Any affected implementation, contract, fixture, dependency, test, verifier, or workflow change makes earlier evidence stale and requires a fresh run.

## Completed controls

- canonical route order and support-triage scenario validation;
- deterministic baseline and bounded scripted-model decision;
- complete decision-schema validation before dispatch;
- non-finite Python confidence rejection;
- strict JSON event serialization without `NaN` or infinity literals;
- invalid-route fail-closed behavior with no specialist invocation;
- schema-valid JSONL events with monotonic sequences;
- exactly one nonblank JSON result line from each verified CLI invocation;
- exact TypeScript CLI option consumption with unknown, positional, and duplicate argument rejection;
- result-to-trace `run_id` binding;
- requested `case_id`, `mode`, and `trace_path` binding;
- exactly one terminal event matching the reported result status;
- `route.selected` and specialist step names bound to the selected route;
- normalized TypeScript/Python result and trace parity;
- prior evidence removal before the first local gate step;
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
