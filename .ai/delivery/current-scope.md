# Current Delivery Scope

## Active phase

M0 — Behavioral parity vertical slice in implementation.

## Current implementation boundary

- support-triage scenario with `billing`, `technical`, and `general` routes;
- deterministic baseline and bounded scripted-model decision;
- TypeScript and Python implementations;
- shared JSON Schema and JSONL event contracts;
- invalid-route fail-closed behavior;
- normalized cross-language parity verification;
- one documented local gate: `python scripts/verify_m0.py`;
- no real provider, Go, persistence, UI, MCP, queue, or framework adapter.

## Current gate

M0 remains incomplete until the exact candidate revision has:

1. passing local evidence in `.boundrelay/m0/verification-evidence.json`;
2. passing GitHub Actions verification for the same revision;
3. review confirmation that no excluded scope entered the change.

## Completion authority

M0 is complete only after current-revision verification evidence satisfies the requirements in `ROADMAP.md` and the foundation design.
