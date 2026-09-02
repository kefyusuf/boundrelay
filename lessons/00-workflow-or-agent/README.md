# Lesson 00 — Workflow or Agent?

## Problem

A support request must be sent to exactly one of three destinations: `billing`, `technical`, or `general`. The first architectural question is not which agent framework to use. It is whether this decision needs model judgment at all.

This lesson implements the same support-triage behavior in TypeScript and Python. Both versions consume the same scenario and schemas, emit the same observable event sequence, and are compared after volatile identifiers are removed.

## Success criteria

A successful implementation must satisfy all M0 invariants:

- billing, technical, and general fixtures select the expected route;
- deterministic and scripted-model modes produce equivalent normalized behavior;
- every event validates against the shared JSON Schema;
- sequence numbers are `1..N` and each run has exactly one terminal event;
- an unknown model route emits `route.rejected`, returns `FAILED`, and invokes no specialist;
- scenario execution needs no API key or network request;
- TypeScript and Python traces pass the same parity verifier.

## Deterministic baseline

Known, stable routing rules belong in ordinary code. The baseline checks a small, explicit keyword set and returns a typed route decision. It is cheaper, faster, and easier to audit than asking a model to decide among three fixed categories.

TypeScript deterministic success:

```bash
npm --prefix lessons/00-workflow-or-agent/typescript run run -- \
  --mode deterministic \
  --case billing-duplicate-charge \
  --trace "$PWD/.boundrelay/manual/ts-deterministic-billing.jsonl"
```

Python deterministic success:

```bash
PYTHONPATH=lessons/00-workflow-or-agent/python/src \
python -m boundrelay_m0 \
  --mode deterministic \
  --case billing-duplicate-charge \
  --trace "$PWD/.boundrelay/manual/py-deterministic-billing.jsonl"
```

## Reason to introduce model judgment

A model becomes defensible when requests are ambiguous, phrased in many ways, or require interpretation that would make deterministic rules brittle. M0 does not call a real provider. A scripted decision provider reproduces model-shaped output offline so the lesson can focus on the trust boundary rather than API setup.

The model path is intentionally bounded: it may propose a route and confidence value, but it cannot dispatch a specialist directly.

## Naive implementation

The unsafe version treats model output as trusted application state and indexes the specialist registry immediately:

```typescript
const route = (rawDecision as {route: Route}).route;
await specialists[route](request);
```

```python
route = cast(Route, raw_decision["route"])
specialists[route](request)
```

A cast does not validate runtime data. If the model returns `unknown-specialist`, the program can select an absent handler, throw in an unrelated place, or accidentally dispatch through an overly permissive fallback.

## Failure injection

The canonical fake-model fixture contains this invalid output:

```yaml
invalid-model-route:
  return: {route: unknown-specialist, confidence: 0.99}
```

Run it in TypeScript:

```bash
npm --prefix lessons/00-workflow-or-agent/typescript run run -- \
  --mode model \
  --case invalid-model-route \
  --trace "$PWD/.boundrelay/manual/ts-model-invalid.jsonl"
```

Run it in Python:

```bash
PYTHONPATH=lessons/00-workflow-or-agent/python/src \
python -m boundrelay_m0 \
  --mode model \
  --case invalid-model-route \
  --trace "$PWD/.boundrelay/manual/py-model-invalid.jsonl"
```

The expected application result is `FAILED` with `INVALID_ROUTE_DECISION`. This is an expected domain failure, so both CLIs still exit successfully after writing the result and trace. Tooling failures and malformed CLI arguments use a non-zero process exit.

## Corrected implementation

The corrected boundary follows a fixed order:

1. obtain a deterministic or scripted-model decision;
2. validate the complete decision against `contracts/routing/route-decision.schema.json`;
3. convert only a schema-valid value to the language-specific `RouteDecision` type;
4. emit `route.selected` and dispatch exactly once, or emit `route.rejected` and fail closed;
5. validate the final result and every event before writing evidence.

The model supplies a proposal. Deterministic code owns validation, state transition, dispatch, and termination.

## Verification evidence

Run the sole documented local M0 gate:

```bash
python scripts/verify_m0.py
```

The certification command requires a clean Git worktree so the tested filesystem content is identical to the revision recorded in evidence. It also removes prior M0 evidence before the first contract or test command.

A passing run writes revision-bound evidence to:

```text
.boundrelay/m0/verification-evidence.json
```

Per-language JSONL traces are written under:

```text
.boundrelay/m0/traces/
```

The verifier executes seven scenario/mode combinations, validates each result and event, checks terminal and sequence invariants, and compares normalized TypeScript and Python outputs.

## Trade-offs

| Dimension | Deterministic baseline | Bounded model decision |
|---|---|---|
| Cost | No inference cost | Adds inference cost with a real provider |
| Latency | Local function execution | Adds model and provider latency |
| Auditability | Rule path is explicit | Requires decision and trace capture |
| Flexibility | Best for known categories and vocabulary | Better for ambiguous or varied language |
| Failure surface | Primarily code and data errors | Adds malformed output, provider, timeout, and budget failures |

## When not to use this pattern

Do not introduce model routing when categories and decision rules are known, regulatory policy requires an exact rule path, latency must remain minimal, or a normal parser/classifier already meets measured quality targets. Do not split each route into an autonomous agent merely because the destinations have different names; a typed function boundary may be sufficient.

## Exercises

1. Add a deterministic synonym without changing either language's observable contract.
2. Add a fixture whose confidence is greater than `1` and confirm it fails before dispatch.
3. Add a fourth route by changing the canonical scenario and schemas first, then observe every parity failure that identifies missing implementations.
4. Extend the verifier with a maximum event-count budget while preserving the seven current cases.
