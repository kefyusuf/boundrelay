# Current Delivery Scope

## Active phase

M0 — Behavioral parity vertical slice complete and verified.

## Verified implementation candidate

- Local authority: `python scripts/verify_m0.py`
- CI workflow: `.github/workflows/m0.yml`
- Candidate revision: `78d91bdf9935d88752fdb938d81c6d4215aa3e99`
- Workflow run: `33651704995`
- Artifact: `m0-verification-78d91bdf9935d88752fdb938d81c6d4215aa3e99`
- Artifact digest: `sha256:de5a561e721fe17fec96c0aa91f7fb532ce0a1e56ae5465ead710e8c753ce7af`
- Verified runtimes: Node.js `v24.19.0`, npm `11.17.0`, Python `3.14.7`
- Result: five contract tests, seven TypeScript tests, seven Python tests, three normalization tests, and seven cross-language parity combinations passed.

This completion record changes delivery metadata only. The pull-request head must also pass the same workflow before merge; behavioral evidence becomes stale after any affected code, contract, fixture, verifier, dependency, or workflow change.

## Completed implementation boundary

- support-triage scenario with `billing`, `technical`, and `general` routes;
- deterministic baseline and bounded scripted-model decision;
- TypeScript and Python implementations;
- shared JSON Schema and JSONL event contracts;
- invalid-route fail-closed behavior;
- normalized cross-language parity verification;
- one documented local gate: `python scripts/verify_m0.py`;
- revision-bound GitHub Actions evidence under `.boundrelay/m0/`;
- no real provider, Go, persistence, UI, MCP, queue, or framework adapter.

## Completion authority

M0 completion is bounded to the implementation and verification scope defined in `ROADMAP.md`, the foundation design, and the accepted implementation plan. Merge remains a separate repository-governance decision.
