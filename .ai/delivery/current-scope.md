# Current Delivery Scope

## Active phase

M0 — Post-review verification corrections implemented; fresh evidence pending.

## Review corrections in scope

- reject non-finite Python route confidence before specialist dispatch;
- require a clean Git worktree before revision-bound local certification;
- remove prior M0 evidence before the first local gate command;
- preserve exact PR-head checkout and hidden artifact upload behavior.

The earlier `78d91bdf9935d88752fdb938d81c6d4215aa3e99` evidence is superseded for completion purposes because verification-affecting source changed after that run.

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

M0 completion must be re-recorded only after the exact corrected candidate revision has passing GitHub Actions evidence and the addressed review threads are rechecked.
