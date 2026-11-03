# Observability: Attribution, Goldens, Evaluation, and Fault Proofs

M6 is the cross-cutting milestone: no new business scenario; the event
envelope stays `1.0`, no new event types — attribution lives on run results
only. If you cannot evaluate behavior against recorded expectations and prove
every declared failure's response on demand, you have logs, not observability.

## Attribution semantics

Every lesson's run result carries a closed, deterministic `attribution` block
(`contracts/observability/attribution.schema.json`):

```json
{"attribution": {"steps": [{"step_name": "worker.order-details", "latency_ms": 10,
                            "cost_cents": 0, "attempts": 1}],
                 "totals": {"latency_ms": 10, "cost_cents": 0, "attempts": 1}}}
```

- **Latency** is never wall-clock: each runner takes an injected deterministic
  clock and sums per-step `latency_ms` from the fixture's `attribution.latency_ms`
  table; wall-clock is never recorded or compared.
- **Cost** is fixture-priced: `attribution.price_table` maps step *kinds* to
  fixed `cost_cents` — `read=0`, `route=0`, `handoff=0`, `synthesis=0`,
  `model_decision=2`, `tool_call=1`, `effect=25`; every executed step's price
  is visible in its scenario fixture, and reads cost zero.
- **Attempts** count real invocations per step name, reconciled across phases
  into one record per step (M4 resume re-execution, M5 submit-window recovery);
  steps appear in first-appearance order; totals equal the per-step sum.

Step names are the runners' names: M0 `classify`/`specialist.<route>` (from
`step.started`); M3-M5 `worker.<id>`/`synthesize`, with M5's effect submission
`effect.submit`. M1 and M2 emit no `step.*` events, so their canonical names
are fixed by the fixture tables: `model`, `tool.<tool>` (M1); `classify`,
`receiver.<receiver>` (M2). `buildAttribution`/`build_attribution` rejects
unknown step names or missing table entries, fail-closed.

## Event-surface audit

`tools/contracts/test_m6_contracts.py` pins `EXPECTED_EVENT_SURFACE`: all 38
canonical cases (M0:7, M1:8, M2:5, M3:6, M4:6, M5:6) mapped to their exact
ordered event-type sequences; M0 keys are `<case_id>@<mode>` (its seven
canonical runs are case/mode combinations), other scenarios key by case id.
Multi-phase cases list the union across phases in phase order — a crash phase
emits no terminal. An undeclared or lost event type fails the audit closed;
the M6 gate compares live traces against this map.

## Golden trajectories and evaluation

Goldens live at `fixtures/goldens/<scenario>/<case>.json` with
`{scenario_id, case_id, languages, result_projection, event_sequence,
attribution}` — language-agnostic; both CLIs must produce the identical
normalized projection. `python tools/evaluate.py` discovers cases from the
fixtures, runs both CLIs offline, normalizes, and compares against the
goldens — fail-closed on missing evidence, validating attribution
completeness. `--regenerate <scenario> <case>` requires a clean worktree and
writes a review-visible diff: a golden is evidence, not a convenience
snapshot. The evaluator is independent of the per-milestone gates.

## Failure matrix and chaos exercises

`fixtures/failure-matrix.yaml` maps every declared failure class (invalid
route, unknown tool, malformed handoff, crash windows, corrupt state, rejected
approval, sink unavailable, duplicate key) to `expected_response` (status,
failure code, exit code, invocation claims) and its proof test identity.
`python tools/chaos.py` replays each fault through the lessons' existing
scripted controls — no new fault machinery — and the observed response must
equal the row. Deterministic only: no random chaos, no wall-clock SLOs, no
metrics backend.

