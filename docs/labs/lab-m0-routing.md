# Lab 0 — Routing fail-closed (M0 support-triage)

**Invariant under attack:** an invalid model route must be rejected *before* any specialist is dispatched; rejection is a domain outcome, not a crash.

## Exercise 1 — M0-F1: invalid route (matrix row `M0-F1`)

```bash
cd lessons/00-workflow-or-agent/typescript
npx tsx src/cli.ts --mode model --case invalid-model-route --trace trace.jsonl
```

Run from `lessons/00-workflow-or-agent/typescript` (or use the evaluator: `python tools/evaluate.py --scenario support-triage --languages ts,py`).

**Expected:** exit `0`, one JSON result line with `status: FAILED`, `failure_code: INVALID_ROUTE_DECISION`, and `specialist_invoked: false`. The trace ends with `run.failed` and contains **no** specialist step events.

Inspect it:

```bash
python tools/inspector.py --trace trace.jsonl
```

The timeline shows `model.completed` (the scripted invalid decision) followed directly by `route.rejected` — no `step.started` for any specialist.

## Exercise 2 — prove the boundary is enforced, not assumed

```bash
python -m unittest tools.contracts.test_contracts -v
python -m unittest tools.parity.test_m0_verification_safety -v
```

The safety suite's mutation tests re-check that a specialist dispatch cannot hide behind an invalid route.

## Discussion

1. Why is rejection a *domain outcome* (exit 0) rather than a tooling error (exit 2)? What would callers conflate if it were exit 2?
2. The scripted model produced a plausible-looking but wrong route. What does "validate decisions before acting on them" cost, and what does skipping it cost?
3. In production, who owns the route enum — the caller or the router? What breaks when they drift?
