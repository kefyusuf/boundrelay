# M8 Mapping — LangGraph (Python) × M3 `order-brief`

Non-authoritative framework mapping per [D-008](../../docs/decisions/D-008-framework-policy.md) and [D-019](../../docs/decisions/D-019-m8-langgraph-m3-mapping.md): the M3 bounded fan-out/fan-in lesson rebuilt on LangGraph 1.2.20 to expose what the framework buys, what must be re-implemented inside it anyway, what it silently changes, and how to leave. The mapping never feeds the goldens, the failure matrix, or the M0–M7 gates; it reads checked-in artifacts only (`fixtures/goprojections/order-brief/`, `fixtures/goldens/order-brief/`) and emits LangGraph's native stream — trace parity with the shared envelope is explicitly out of scope.

## Setup and run

LangGraph is pinned exactly (`python/requirements-dev.txt`: `langgraph==1.2.20` plus the shared `jsonschema[format]==4.26.0` pin) and is installed at setup only; runs are offline with deterministic scripted nodes — no LLM calls, no network.

```bash
# repo venv already carries the pin; or create a mapping-local venv:
python -m venv .venv-m8 && .venv-m8/Scripts/python -m pip install -r mappings/langgraph-m3/python/requirements-dev.txt
# suite (repo venv python, mapping src on PYTHONPATH):
PYTHONPATH=mappings/langgraph-m3/python/src .venv/Scripts/python.exe -m unittest discover -s mappings/langgraph-m3/python/tests -t mappings/langgraph-m3/python/tests
# one case through the graph (one JSON result line on stdout; exit 0 domain, 2 tooling):
PYTHONPATH=mappings/langgraph-m3/python/src .venv/Scripts/python.exe -m boundrelay_m3_langgraph.cli --case parallel-complete --trace .boundrelay/manual/m8-native-stream.jsonl
# naive teaching mode (uncapped, default propagation; may crash by design):
PYTHONPATH=mappings/langgraph-m3/python/src .venv/Scripts/python.exe -m boundrelay_m3_langgraph.cli --case parallel-partial-failure --mode naive --trace .boundrelay/manual/m8-naive.jsonl
```

All six parity cases reproduce the M3 goldens' `result_projection` (status, canonical `worker_outcomes` with failure codes, `synthesis_invoked`, brief, `failure_code`, `peak_concurrency` 2/1) with attribution from the same fixture tables — proven by `python/tests/test_graph_parity.py::SixCaseParityTests` (deep-equal minus `run_id`/`trace_path`, schema-valid against `contracts/results/order-brief-result.schema.json`).

## D-008 question 1 — What the framework provides

Graph topology (`StateGraph`, `START`/`END`, conditional edges), parallel branch dispatch (the three worker nodes run concurrently in one superstep), state channels with reducers (per-worker outcome slots; the naive graph's arrival-ordered shared list), a native stream (`stream_mode="updates"` chunks, written verbatim to `--trace`), and optional built-in checkpointing (deliberately unused here — see question 3).

Proof: `python/tests/test_graph_parity.py` drives all six cases through the real compiled graph; `test_native_stream_trace_is_written` shows the native chunks (`worker.order-details`, `worker.payment-status`, `worker.delivery-status`, `collect`, `synthesize`, `finalize`).

## D-008 question 2 — What remains application responsibility

The M3 failure taxonomy (`WORKER_EXECUTION_FAILED` for declared errors vs `INVALID_WORKER_OUTPUT` for invalid returns) is handled inside each node and validated before publication (`graph.worker_outcome`, `results.validate_result`); canonical ordering of outcomes and brief sections is structural (one private state channel per worker + `results.canonicalize_outcomes`); synthesis is one node gated on >=1 success via a conditional edge; attribution is assembled by the mapping from the same fixture tables (`attribution.build_attribution`, totals = sum); and the bounded-admission invariant is re-established by `graph.BoundedWorkerExecutor`.

Proof: `python/tests/test_taxonomy.py` (declared failure → `PARTIAL` with exactly `["delivery-status"]` missing; invalid output → `PARTIAL`, `UNKNOWN` never published; all-failed → `FAILED`/`ALL_WORKERS_FAILED`, no synthesis), `python/tests/test_order_independence.py` (brief equal for feasible permutations; canonical order invariant under all six permutations), `python/tests/test_attribution.py` (table × attempts, totals = sum, golden totals 48/33).

## D-008 question 3 — What becomes hidden or changes

The framework's own execution telemetry replaces the shared event envelope (native `updates` stream only — trace parity excluded by design). Admission timing is framework-chosen: parallel dispatch is uncapped by default, so `peak_concurrency` is whatever the framework produces — the naive graph honestly records 3. Default error propagation must be overridden node-by-node to preserve the taxonomy: unmodified, a declared worker error crashes the entire graph run. Built-in checkpointing (unused here) would adopt framework-owned state formats — the M4 lesson's counterpoint.

**The bounded-admission cost (the centerpiece finding):** LangGraph exposes no first-class 1/2-slot semaphore primitive. Re-establishing the cap inside the framework costs `BoundedWorkerExecutor` — canonical-order slot admission, completion-order release gates, a concurrency ledger — all application code running inside the worker nodes while the framework still dispatches all three branches at once. The wrapper makes `peak_concurrency` deterministic (2 parallel / 1 sequential) at the price of owning admission in the app instead of the framework, plus a deadlock guard that fails the run fast instead of hanging.

Proof: `python/tests/test_naive_regression.py` (uncapped rendezvous proves 3-way overlap and records peak 3 vs the corrected 2; declared error crashes the naive run; invalid `UNKNOWN` output becomes a fact; naive results fail the closed schema) and `python/tests/test_graph_parity.py` (corrected runs match the goldens' capped projections exactly).

## D-008 question 4 — How to exit the abstraction

The mapping imports the canonical fixtures, goldens, and schema shapes only through their checked-in artifacts (`fixtures.py` reads `fixtures/goprojections/order-brief/` and `fixtures/goldens/order-brief/`; tests validate against `contracts/results/order-brief-result.schema.json`). Nothing outside `mappings/langgraph-m3/` references the package or `langgraph`: `tools/contracts/test_m8_contracts.py` fails closed on any reference under `lessons/`, `contracts/`, `tools/`, `scripts/`, `go/` outside a precise allowlist. Deleting `mappings/` leaves every lesson, gate, golden, and evidence path intact — the canonical lesson (`lessons/03-parallel-fanout-fanin/`) remains the source of truth and the exit path.

## Files

| File | Responsibility |
|---|---|
| `python/pyproject.toml` | Package `boundrelay-m3-langgraph`; no runtime deps |
| `python/requirements-dev.txt` | Exact `langgraph==1.2.20` + shared `jsonschema` pin |
| `python/src/boundrelay_m3_langgraph/fixtures.py` | Strict fixture/golden loading (checked-in artifacts only) |
| `python/src/boundrelay_m3_langgraph/graph.py` | Corrected graph + `BoundedWorkerExecutor` (bounded admission) |
| `python/src/boundrelay_m3_langgraph/naive.py` | Naive graph (uncapped, default propagation) |
| `python/src/boundrelay_m3_langgraph/results.py` | M3-schema result assembly + structural validation |
| `python/src/boundrelay_m3_langgraph/attribution.py` | Attribution from fixture tables (M6 rules) |
| `python/src/boundrelay_m3_langgraph/cli.py` | `--case/--mode/--trace`; exit 0 domain, 2 tooling |
| `python/tests/` | Mapping suite (fixtures, parity, taxonomy, ordering, naive, attribution, CLI) |
