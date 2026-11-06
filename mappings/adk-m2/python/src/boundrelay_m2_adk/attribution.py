"""Deterministic attribution for the P5b mapping, mirroring the M2 rules.

Per-step latency = fixture table x attempts; totals = sum of steps.
The classify step is priced by the router mode (model_decision for
model mode, route for code mode); receiver.<name> steps are handoffs.
"""
from .fixtures import STEP_KINDS


def step_kind(step_name, mode):
    if step_name == "classify":
        return "model_decision" if mode == "model" else "route"
    if type(step_name) is str and step_name.startswith("receiver."):
        return "handoff"
    raise ValueError(f"Unknown attribution step: {step_name}")


def build_attribution(step_records, tables, mode):
    """step_records: [(step_name, attempts), ...]; tables: fixture tables."""
    latency_table = tables["latency_ms"]
    price_table = tables["price_table"]
    steps = []
    totals = {"latency_ms": 0, "cost_cents": 0, "attempts": 0}
    for step_name, attempts in step_records:
        if type(attempts) is not int or attempts < 1:
            raise ValueError(f"Invalid attribution attempts for {step_name}")
        if step_name not in latency_table:
            raise ValueError(f"Unknown attribution step: {step_name}")
        kind = step_kind(step_name, mode)
        if kind not in price_table:
            raise ValueError(f"Unknown attribution price kind: {kind}")
        record = {
            "step_name": step_name,
            "latency_ms": latency_table[step_name] * attempts,
            "cost_cents": price_table[kind] * attempts,
            "attempts": attempts,
        }
        steps.append(record)
        totals["latency_ms"] += record["latency_ms"]
        totals["cost_cents"] += record["cost_cents"]
        totals["attempts"] += attempts
    if not steps:
        raise ValueError("Attribution requires at least one executed step")
    return {"steps": steps, "totals": totals}
