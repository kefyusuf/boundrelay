# BoundRelay Roadmap

The roadmap is milestone-driven. A milestone is complete only when its verification evidence is produced against the current revision.

## M0 — Behavioral parity vertical slice

**Goal:** Prove the repository's teaching and verification model with one small scenario.

### Scope

- One support-triage scenario.
- Deterministic routing baseline.
- TypeScript implementation.
- Python implementation.
- Shared scenario and event contracts.
- Deterministic fake decision provider; no API key.
- JSONL trace output.
- One injected invalid-route failure.
- Cross-language normalized trace comparison.
- Unit tests and one end-to-end parity test.
- English lesson documentation and Turkish overview.

### Completion evidence

- Fresh clone setup succeeds using documented commands.
- Both implementations run without network access.
- Both produce schema-valid traces.
- Both reject an unknown route deterministically.
- Both satisfy the same behavioral invariants.
- CI executes the same verification path used locally.

## M1 — Bounded single-agent tool loop

- Model–tool–observation loop.
- Structured tool schemas.
- Maximum step and token budgets.
- Unknown tool, malformed arguments, timeout, and tool failure cases.
- Deterministic fake model trajectory.
- Explanation of when a direct function call is better.

## M2 — Routing and handoff

- Code router versus LLM router.
- Typed handoff envelope.
- Sender intent versus receiver input trace.
- Fallback and confidence policy.
- Handoff failure and context-loss examples.

## M3 — Parallel fan-out and fan-in

- Independent read-only workers.
- Bounded concurrency.
- Partial failure represented explicitly.
- Deterministic merge contract.
- A single synthesizer owns the final write.

## M4 — Durable state and recovery

- Run state separate from user-facing history.
- Checkpoints.
- Resume versus retry.
- Cancellation.
- Replay from a prior step.
- Revision-bound evidence.

## M5 — Side effects, idempotency, and human approval

- Idempotency keys.
- Safe retry boundaries.
- Approval before irreversible action.
- Audit records.
- Explicit `UNKNOWN` outcome when external reality cannot be proven.

## M6 — Observability, evaluation, and fault injection

- Run, step, model, tool, handoff, checkpoint, and approval events.
- Cost, latency, and retry attribution.
- Golden trajectories and behavioral probes.
- Regression evaluation.
- Failure matrix and chaos-style exercises.

## M7 — Go parity

- Implement stable lessons idiomatically in Go.
- Preserve shared contracts and invariants.
- Demonstrate contexts, cancellation, bounded concurrency, and explicit errors.
- Add Go to cross-language parity CI.

## M8 — Framework mappings

Frameworks are introduced only after first-principles implementations are understood.

Initial mapping candidates:

- OpenAI Agents SDK;
- LangGraph;
- Google ADK;
- Mastra;
- Eino for Go.

Mappings must show what the framework provides, what remains application responsibility, what becomes hidden, and how to exit the abstraction.

## v1.0 exit criteria

- Lessons 00–10 complete in TypeScript and Python.
- Stable lessons implemented in Go.
- Offline deterministic mode for every lesson.
- Shared trace inspector.
- Fault-injection exercises.
- Cross-language parity CI.
- Production checklist covering state, recovery, side effects, permissions, observability, evaluation, and cost controls.

## v1.0 track — sequenced work packages

The milestone track (M0–M8) is complete and certified. The v1.0 exit criteria are delivered through five sequenced packages; each keeps the established discipline (design → plan → implementation → revision-bound evidence), scoped to stay reviewable.

| Package | Deliverable | Scope | Depends on |
|---|---|---|---|
| **P1 — Production checklist** | `docs/production-checklist.md` + executable linkage test | Maps every checklist claim (state, recovery, side effects, permissions, observability, evaluation, cost) to its proving gate/invariant; residual gaps explicit | — |
| **P2 — Trace inspector** ✅ | `tools/inspector.py` + self-contained offline HTML viewer | Renders any lesson's JSONL trace (event lifecycle, state transitions, payloads, result/attribution via `--result`); zero runtime deps; fail-closed on invalid traces | P1 |
| **P3 — Fault-injection labs** | Per-lesson exercise packs (`docs/labs/`) | Each lesson's declared faults as runnable exercises with commands, expected responses, and discussion questions; reuses the M6 matrix | P2 |
| **P4 — Remaining Go ports** | Go runtimes for M1, M2, M4, M5 | Extends D-018's showcase-pair decision; three-language parity for 25 more case keys; `verify_m9.py`-style authority extension | P2 |
| **P5 — Framework mappings** | LangGraph×M4, OpenAI Agents SDK×M1, Google ADK×M2, Mastra×M3 (TS), Eino×M3 (Go) | Extends D-019's single-mapping pattern; one mapping per package increment, same isolation rules | P1, P4 (for Eino) |

Package order is by effort-per-value: P1 documents what exists, P2/P3 make it inspectable and teachable, P4/P5 expand language and framework coverage. Each package lands as its own reviewed PR series; nothing in the track changes the certified M0–M8 behavior.
