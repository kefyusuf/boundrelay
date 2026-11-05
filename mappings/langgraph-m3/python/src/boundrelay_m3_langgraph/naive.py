"""The naive M3 LangGraph graph: uncapped dispatch, default propagation.

This is the teaching regression, kept honest. It trusts LangGraph's
defaults everywhere: all three branches dispatch at once (no admission
cap - proven by a three-way rendezvous barrier inside the nodes), worker
returns are published unvalidated (an invalid output becomes a fact),
and a declared worker error propagates by default, crashing the whole
graph run. Its results are asserted to diverge from the closed schema.
"""
import json
import operator
import threading
from pathlib import Path
from typing import Annotated, Optional, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from . import fixtures
from .graph import WorkerExecutionError

WORKER_IDS = fixtures.WORKER_IDS
RENDEZVOUS_TIMEOUT_SECONDS = 30.0


class NaiveState(TypedDict, total=False):
    """Shared sections list: arrival-ordered appends, the naive defect."""

    sections: Annotated[list, operator.add]
    result: Optional[dict]


class UncappedLedger:
    """Records how many workers actually overlapped (recorded, not
    normalized): the naive run has no cap, so all three can overlap."""

    def __init__(self):
        self._lock = threading.Lock()
        self._active = 0
        self._peak = 0

    def enter(self):
        with self._lock:
            self._active += 1
            self._peak = max(self._peak, self._active)

    def exit(self):
        with self._lock:
            self._active -= 1

    @property
    def peak(self):
        with self._lock:
            return self._peak


def build_naive_graph(case, ledger, run_id, trace_path):
    """The naive StateGraph: uncapped parallel dispatch, shared arrivals."""
    rendezvous = threading.Barrier(len(WORKER_IDS),
                                   timeout=RENDEZVOUS_TIMEOUT_SECONDS)
    builder = StateGraph(NaiveState)
    for worker_id in WORKER_IDS:
        builder.add_node(f"worker.{worker_id}",
                         make_naive_worker_node(case, ledger, worker_id,
                                                rendezvous))
        builder.add_edge(START, f"worker.{worker_id}")
        builder.add_edge(f"worker.{worker_id}", "synthesize")

    def synthesize(state):
        sections = state.get("sections", [])
        result = {
            "schema_version": "1.0", "run_id": run_id,
            "scenario_id": "order-brief", "case_id": case.case_id,
            "execution_mode": "parallel",
            "concurrency_limit": None,
            "peak_concurrency": ledger.peak,
            "order_id": case.order_id, "status": "SUCCEEDED",
            "worker_outcomes": [
                {"worker_id": section["worker_id"], "status": "SUCCEEDED",
                 "output": section["output"], "failure_code": None}
                for section in sections],
            "synthesis_invoked": True,
            "brief": {"order_id": case.order_id, "sections": sections,
                      "missing_workers": [], "complete": True},
            "failure_code": None, "trace_path": trace_path,
            "attribution": None,
        }
        return {"result": result}

    builder.add_node("synthesize", synthesize)
    builder.add_edge("synthesize", END)
    return builder.compile()


def make_naive_worker_node(case, ledger, worker_id, rendezvous):
    def node(state):
        ledger.enter()
        try:
            # Proves the framework dispatched all three branches at once:
            # with any admission cap this rendezvous would break.
            rendezvous.wait()
            instruction = case.instructions[worker_id]
            if instruction["operation"] == "raise":
                # Default propagation: no taxonomy handling, the declared
                # error crashes the whole graph run.
                raise WorkerExecutionError("Declared worker failure")
            return {"sections": [{"worker_id": worker_id,
                                  "output": instruction["output"]}]}
        finally:
            ledger.exit()

    return node


def run_naive(case_id, trace_path):
    """Run one case through the naive graph, streaming the native stream
    to the trace file. Declared worker errors propagate (exit-path 2);
    the flushed stream prefix stays inspectable."""
    case = fixtures.load_case(case_id)
    run_id = str(uuid4())
    ledger = UncappedLedger()
    app = build_naive_graph(case, ledger, run_id, trace_path)
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
        raise RuntimeError("Naive run produced no result")
    return merged["result"]
