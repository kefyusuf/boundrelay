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
