"""The corrected M3 LangGraph graph: taxonomy-preserving, canonically
ordered, bounded admission re-established inside the framework.

Topology: START -> three parallel scripted-worker nodes -> collect ->
(synthesize | finalize) -> END. Each worker owns a private state channel,
so canonical outcome ordering is structural, not arrival-based. Failure
handling lives inside the nodes: a declared error becomes a FAILED
outcome with WORKER_EXECUTION_FAILED; an invalid return becomes FAILED
with INVALID_WORKER_OUTPUT - both validated before publication. The
framework's parallel dispatch is uncapped by default; the application
re-establishes the 2-slot cap through BoundedWorkerExecutor (the bounded
executor wrapper) - the mapping's centerpiece cost.
"""
import json
import threading
import time
from pathlib import Path
from typing import Optional, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from . import attribution as attribution_module
from . import fixtures, results

WORKER_IDS = fixtures.WORKER_IDS
SLOT_BY_WORKER = {
    "order-details": "order_details_outcome",
    "payment-status": "payment_status_outcome",
    "delivery-status": "delivery_status_outcome",
}
SLOT_KEYS = tuple(SLOT_BY_WORKER[worker_id] for worker_id in WORKER_IDS)
DEADLOCK_GUARD_SECONDS = 60.0


class CorrectedState(TypedDict, total=False):
    """Per-worker outcome channels + canonical fan-in + published result.

    Each slot channel is written by exactly one node, so the state reducer
    preserves per-worker slots and canonical order is structural.
    """

    order_details_outcome: Optional[dict]
    payment_status_outcome: Optional[dict]
    delivery_status_outcome: Optional[dict]
    outcomes: list
    brief: Optional[dict]
    result: Optional[dict]


class WorkerExecutionError(Exception):
    """Declared worker failure (the fixture's 'raise' instruction)."""


class ToolingInterrupted(RuntimeError):
    """Unexpected implementation error: the run drains and propagates."""
class BoundedWorkerExecutor:
    """The bounded executor wrapper re-establishing M3 admission caps.

    LangGraph admits all parallel branch nodes at once (uncapped). This
    wrapper caps concurrent workers at `limit` (2 for parallel, 1 for
    sequential), admits in canonical worker order (so the fixture's
    completion order stays feasible), releases workers along the fixture's
    completion_order (a slot is occupied until the validated outcome is
    recorded), and records the observed peak concurrency. Deadlock guard:
    bounded waits raise ToolingInterrupted instead of hanging forever.
    """

    def __init__(self, completion_order, limit, worker_ids=WORKER_IDS):
        if limit not in (1, 2):
            raise ValueError("Admission limit must be 1 or 2")
        self.completion_order = tuple(completion_order)
        self.limit = limit
        self.worker_ids = tuple(worker_ids)
        self._cond = threading.Condition()
        self._active = []
        self._entered = set()
        self._cursor = 0
        self._peak = 0
        self._broken = False

    @property
    def observed_peak(self):
        with self._cond:
            return self._peak

    def _wait(self, predicate, what):
        deadline = time.monotonic() + DEADLOCK_GUARD_SECONDS
        while not predicate():
            if self._broken:
                raise ToolingInterrupted("Run drained by an unexpected error")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ToolingInterrupted(f"Admission guard tripped: {what}")
            self._cond.wait(remaining)

    def enter(self, worker_id):
        """Occupy a slot: blocks until a slot is free AND every
        canonical-prior worker has already entered."""
        with self._cond:
            index = self.worker_ids.index(worker_id)

            def admitted():
                prior_pending = any(candidate not in self._entered
                                    for candidate in
                                    self.worker_ids[:index])
                return len(self._active) < self.limit and not prior_pending

            self._wait(admitted, f"enter({worker_id})")
            self._entered.add(worker_id)
            self._active.append(worker_id)
            self._peak = max(self._peak, len(self._active))
            # A new entrant can unblock both slot waiters and release gates.
            self._cond.notify_all()

    def await_release(self, worker_id):
        """Completion-order gate: run your instruction on your turn. The
        first parallel release additionally waits for the whole first wave
        to have entered (proves the cap binds: peak >= limit)."""
        with self._cond:
            first_wave = (self._cursor == 0 and self.limit == 2
                          and len(self.worker_ids) > self.limit)
            required = min(self.limit, len(self.worker_ids)) if first_wave else 0

            def released():
                if self.completion_order[self._cursor] != worker_id:
                    return False
                return len(self._entered) >= required

            self._wait(released, f"release({worker_id})")

    def record(self, worker_id):
        """Record the validated outcome: the slot frees, the gate advances."""
        with self._cond:
            if worker_id in self._active:
                self._active.remove(worker_id)
            self._cursor += 1
            self._cond.notify_all()

    def abandon(self, worker_id):
        """Unexpected error path: drain the run and fail every waiter."""
        with self._cond:
            self._broken = True
            if worker_id in self._active:
                self._active.remove(worker_id)
            self._cond.notify_all()


def worker_outcome(worker_id, instruction, order_id):
    """Taxonomy-preserving failure handling INSIDE the node.

    Declared error -> FAILED/WORKER_EXECUTION_FAILED. Invalid return ->
    FAILED/INVALID_WORKER_OUTPUT (validated before publication). Only
    unexpected implementation errors escape the node.
    """
    if instruction["operation"] == "raise":
        raise WorkerExecutionError("Declared worker failure")
    validation = results.validate_worker_output(
        worker_id, instruction["output"], order_id)
    if validation.valid:
        return {"worker_id": worker_id, "status": "SUCCEEDED",
                "output": validation.value, "failure_code": None}
    return {"worker_id": worker_id, "status": "FAILED", "output": None,
            "failure_code": "INVALID_WORKER_OUTPUT"}


def make_worker_node(case, executor, worker_id):
    def node(state):
        executor.enter(worker_id)
        executor.await_release(worker_id)
        try:
            outcome = worker_outcome(worker_id,
                                     case.instructions[worker_id],
                                     case.order_id)
        except WorkerExecutionError:
            outcome = {"worker_id": worker_id, "status": "FAILED",
                       "output": None,
                       "failure_code": "WORKER_EXECUTION_FAILED"}
        except BaseException:
            executor.abandon(worker_id)
            raise
        executor.record(worker_id)
        return {SLOT_BY_WORKER[worker_id]: outcome}

    return node


def build_corrected_graph(case, executor, run_id, trace_path):
    """The corrected LangGraph StateGraph for one M3 case run.

    The framework dispatches the three worker branches concurrently and
    uncapped; BoundedWorkerExecutor re-establishes the M3 cap inside the
    nodes (the documented cost of bounded admission on LangGraph).
    """
    builder = StateGraph(CorrectedState)
    for worker_id in WORKER_IDS:
        builder.add_node(f"worker.{worker_id}",
                         make_worker_node(case, executor, worker_id))
        builder.add_edge(START, f"worker.{worker_id}")
        builder.add_edge(f"worker.{worker_id}", "collect")

    def collect(state):
        outcomes = results.canonicalize_outcomes(
            [state[slot] for slot in SLOT_KEYS], case.order_id)
        return {"outcomes": list(outcomes)}

    def route(state):
        if any(outcome["status"] == "SUCCEEDED"
               for outcome in state["outcomes"]):
            return "synthesize"
        return "finalize"

    def synthesize(state):
        return {"brief": results.synthesize_brief(case.order_id,
                                                  state["outcomes"])}
    def finalize(state):
        outcomes = state["outcomes"]
        records = [(f"worker.{worker_id}", 1) for worker_id in WORKER_IDS]
        if any(outcome["status"] == "SUCCEEDED" for outcome in outcomes):
            records.append(("synthesize", 1))
        attribution = attribution_module.build_attribution(records, {
            "latency_ms": case.latency_ms,
            "price_table": case.price_table,
        })
        result = results.assemble_result(
            run_id=run_id, trace_path=trace_path, case=case,
            peak_concurrency=executor.observed_peak, outcomes=outcomes,
            attribution=attribution)
        return {"result": result}

    builder.add_node("collect", collect)
    builder.add_node("synthesize", synthesize)
    builder.add_node("finalize", finalize)
    builder.add_conditional_edges("collect", route,
                                  {"synthesize": "synthesize",
                                   "finalize": "finalize"})
    builder.add_edge("synthesize", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile()


def run_corrected(case_id, trace_path):
    """Run one case through the corrected graph, streaming the native
    LangGraph stream to the trace file; returns the published result."""
    case = fixtures.load_case(case_id)
    run_id = str(uuid4())
    executor = BoundedWorkerExecutor(case.completion_order, case.limit)
    app = build_corrected_graph(case, executor, run_id, trace_path)
    merged = {}
    trace = Path(trace_path)
    trace.parent.mkdir(parents=True, exist_ok=True)
    with trace.open("w", encoding="utf-8") as handle:
        try:
            for chunk in app.stream({}, stream_mode="updates"):
                handle.write(json.dumps(chunk, ensure_ascii=True,
                                        allow_nan=False) + "\n")
                for delta in chunk.values():
                    if isinstance(delta, dict):
                        merged.update(delta)
        finally:
            handle.flush()
    if "result" not in merged:
        raise RuntimeError("Corrected run produced no publishable result")
    return merged["result"]
