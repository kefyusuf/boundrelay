# P5d Mapping — Eino (Go) × M3 `order-brief`

Non-authoritative framework mapping per [D-008](../../docs/decisions/D-008-framework-policy.md): the M3 bounded fan-out/fan-in lesson rebuilt on Eino, CloudWeGo's Go LLM framework (`github.com/cloudwego/eino v0.9.22`) to expose what the framework buys, what must be re-implemented inside it anyway, what it silently changes, and how to leave. The mapping never feeds the goldens, the failure matrix, or the M0–M7 gates; it reads checked-in artifacts only (`fixtures/goprojections/order-brief/`, `fixtures/goldens/order-brief/`) and emits Eino's native callback stream — event-envelope trace parity is explicitly out of scope.

## Setup and run

The engine is pinned exactly (`go/go.mod`: `require github.com/cloudwego/eino v0.9.22`, resolved by the committed `go.sum`; discovered empirically as the latest release at mapping time) in the mapping's own Go module `boundrelay-m3-eino`, installed at setup only. M3 has no model at all, and Eino's Graph runs deterministic lambda nodes as plain functions: a graph with only `InvokableLambda` nodes needs no LLM, no API key, and no network — proven offline by `internal/mapping/mapping_test.go` `TestOfflineProof`, which swaps `http.DefaultTransport` for an exploding RoundTripper and then drives all six cases through the real compiled graph.

```bash
# build + suite (the module is self-contained: it mirrors the closed M3
# contract shapes locally and imports nothing from the repo's go/ module):
cd mappings/eino-m3/go && go build ./... && go test ./...
# one case through the graph (one JSON result line on stdout; exit 0 domain, 2 tooling):
go run ./cmd --case parallel-complete --trace .boundrelay/manual/p5d-callbacks.jsonl
# naive teaching mode (uncapped rendezvous, default propagation; exits 2 by design):
go run ./cmd --mode naive --case parallel-partial-failure --trace .boundrelay/manual/p5d-naive.jsonl
```

All six parity cases reproduce the M3 goldens' `result_projection` (status, canonical `worker_outcomes` with failure codes, `synthesis_invoked`, brief, `failure_code`, `peak_concurrency` 2/1, attribution totals 48/33) — proven by `internal/mapping/mapping_test.go` `TestParitySixCases` (deep-equal of the JSON projection minus `run_id`/`trace_path` against the golden `result_projection`, attribution deep-equal, every published result re-checked against the hand-mirrored closed validator).

## D-008 question 1 — What the framework provides

The workflow graph itself (`compose.NewGraph[I,O]` + `AddLambdaNode` + `AddEdge` composition compiled once per run, DAG trigger mode `WithNodeTriggerMode(AnyPredecessor)`), the worker boundary as lambda nodes (the seam the three scripted workers plug into), parallel branch dispatch (three edges out of `START` = three concurrent node executions), a framework-native fan-in (three edges into the collector merge into one `map[string]any` input keyed by the producers' publish keys — the collector reorders canonically by looking up the known keys), the conditional as a first-class `GraphBranch` (the synthesis gate routes `collect` → `synthesize` exactly when ≥ 1 worker succeeded, → `finalize` otherwise; an unselected branch end is skipped and the skip propagates, so finalize receives exactly one map per run — with the brief when synthesis ran, without it when all workers failed), the run machinery (`Compile`/`Invoke`), and the native callback stream (`callbacks.Handler` with `OnStart`/`OnEnd`/`OnError` per node carrying `RunInfo` — written verbatim to `--trace` as JSONL `node_start`/`node_end`/`node_error` lines).

Proof: `TestParitySixCases` drives all six cases through the real compiled graph; `TestSingleSynthesisInvocationViaTrace` reads the trace and shows exactly one `synthesize` start/end on success/partial runs and zero on the all-failed run (single synthesis is structural: the node is reachable only through the branch); `TestOfflineProof` runs everything with every network attempt exploding.

## D-008 question 2 — What remains application responsibility

The whole M3 discipline: the scripted workers themselves (the fixture instructions are plain data; the mapping owns their interpretation), the M3 failure taxonomy inside each node (`mapping.workerOutcome`: declared error → `WORKER_EXECUTION_FAILED`, invalid return → `INVALID_WORKER_OUTPUT` via `results.ValidateWorkerOutput` — validated before publication; only unexpected implementation errors escape the node), the completion-order semantics (per-worker release gates over the fixture's `completion_order` — the framework has no notion of a scripted completion schedule), single synthesis ownership (the `synthesize` node is the only caller of `results.SynthesizeBrief`, reachable only through the branch), canonical ordering (the keyed-map fan-in merged by the engine, reordered in `CanonicalWorkerIDs` order by the collector — `results.CanonicalizeOutcomes` re-checks the fan-in), attribution (`attribution.Build` from the same fixture tables, totals = sum, M6 rules), and the closed result shape itself (`results` mirrors the checked-in schema by hand, including the totals = sum invariant the JSON schema cannot express).

Proof: `TestTaxonomyPreservedInsideNodes` (declared failure → PARTIAL with exactly `["delivery-status"]` missing; invalid `UNKNOWN` output never published; all-failed → FAILED/`ALL_WORKERS_FAILED` with `synthesis_invoked` false and a null brief), `TestCanonicalOrderingUnderOutOfOrderCompletion` (canonical order invariant under the scripted out-of-order schedule), `TestParitySixCases` (identical briefs and golden attribution), the `results`/`fixtures` package tests (the structural validator rejects peak 3, published `MYSTERY` outputs, failed-without-code, broken totals, infeasible schedules, and off-taxonomy instructions).

## D-008 question 3 — What becomes hidden or changes

**The bounded-admission cost (the centerpiece finding):** Eino provides no concurrency bound at all. In the engine, every ready node becomes a `task` and the task manager dispatches it with `go t.execute(currentTask)` (`compose/graph_manager.go`, `submit`); the compile options offer `WithMaxRunSteps` (a step *count*, and it is rejected in DAG mode) but no concurrency primitive — no semaphore, no worker pool, no per-branch cap. Probed empirically against v0.9.22: an instrumented three-branch rendezvous records **peak 3** through the Graph API in *both* trigger modes (Pregel `AllPredecessor` and DAG `AnyPredecessor`) and through the Workflow field-mapping API (all three compile down to the same runner). Re-establishing the cap therefore costs `mapping.BoundedExecutor` — canonical-order slot admission, completion-order release gates, a first-wave binding (the first parallel release waits until `limit` workers have entered, proving the cap binds), a concurrency ledger, and a deadlock guard that fails the run fast instead of hanging — all application code running inside the worker nodes while the engine still dispatches all three branches at once. The wrapper makes `peak_concurrency` deterministic (2 parallel / 1 sequential) at the price of owning admission in the app instead of the framework.

Also rewritten or changed by the framework: **fan-in merge is by map key, not by identity** — multiple edges into one node shallow-merge the upstream `map[string]any` outputs, so the workers publish under their own keys and the collector does the canonical merge (no getStepResult-style random access; on the branch-to-finalize path finalize reads the collector's own output). **Two composition APIs, one engine:** the Workflow (field-mapping) API refuses to merge three entire outputs into one node ("entire output has already been mapped" — each input needs explicit `MapFields`), while the Graph API merges keyed maps natively; both dispatch identically unboundedly. **Node callbacks fire with empty names** unless each node is explicitly given `compose.WithNodeName` — the mapping names every node or the trace is anonymous. **`END` and `start` are reserved keys** in the Workflow API, and **branch end nodes must be added before `AddBranch`**. **No step limit in DAG mode** (`WithMaxRunSteps` panics there), and a declared worker failure **propagates by default**: without the in-node taxonomy, one node error fails the whole run (the naive regression) — though the trace prefix is still flushed. A skipped branch end is silent (no skip event in the callback stream): the all-failed run's trace simply never mentions `synthesize`.

Proof: `TestBoundedAdmission` (deterministic peaks 2/1 through the real graph; the first-wave binding; third-admission blocked until a slot frees; the guard tripping on a circular-wait schedule and draining every waiter; `abandon` failing waiters), `TestNaiveRegression` (the 3-way rendezvous records peak 3 vs the corrected 2; `UNKNOWN` published as a fact; a declared error crashes the run with the trace prefix flushed; naive results fail the closed validator), `TestSingleSynthesisInvocationViaTrace` (named nodes and exactly-once synthesis in the trace).

## D-008 question 4 — How to exit the abstraction

The mapping imports the canonical fixtures, goldens, and schema shapes only through their checked-in artifacts (`internal/fixtures` reads `fixtures/goprojections/order-brief/` and `fixtures/goldens/order-brief/`; the parity tests re-check published results against the hand-mirrored closed validator). The Go module is fully self-contained: it mirrors the contract shapes locally and imports nothing from the repo's `go/` module. Nothing outside `mappings/eino-m3/` references the module or `eino`: `tools/contracts/test_p5d_contracts.py` fails closed on any `eino`/`cloudwego`/mapping token under `lessons/`, `contracts/`, `tools/`, `scripts/`, `go/` outside a precise allowlist (with a NUL-byte binary guard so checked-in toolchain binaries cannot forge a hit), plus a Go-import scan and a Python-import scan for defense in depth. Deleting `mappings/` leaves every lesson, gate, golden, and evidence path intact — the canonical lesson (`lessons/03-parallel-fanout-fanin/`) remains the source of truth and the exit path.

Proof: `tools/contracts/test_p5d_contracts.py` (isolation scan, manifest pin, module skeleton, offline compile probe, parity keys) and `TestOfflineProof` (every network attempt explodes; the real graph completes all six case shapes anyway, with no API key and no model).

## Files

| File | Responsibility |
|---|---|
| `go/go.mod`, `go/go.sum` | Own module `boundrelay-m3-eino`; single dependency `github.com/cloudwego/eino v0.9.22` (go.sum committed) |
| `go/internal/fixtures/fixtures.go` | Strict fixture/golden loading (checked-in artifacts only, feasibility checks) |
| `go/internal/results/results.go` | M3-schema result assembly + structural validation (the closed shapes, hand-mirrored) |
| `go/internal/attribution/attribution.go` | Attribution from fixture tables (M6 rules) |
| `go/internal/mapping/executor.go` | `BoundedExecutor`: canonical slot admission, completion-order release gates, first-wave binding, guard |
| `go/internal/mapping/mapping.go` | Eino wiring: worker/collect/branch/synthesize/finalize graph, callback trace writer |
| `go/internal/mapping/naive.go` | Naive graph (uncapped 3-way rendezvous, default propagation, unvalidated publication) |
| `go/internal/cli/cli.go`, `go/cmd/main.go` | `--case/--mode/--trace`; exit 0 domain, 2 tooling |
| `go/internal/**/*_test.go` | Mapping suite (fixtures, results, attribution, parity, taxonomy, ordering, admission, synthesis, naive, CLI, offline) |
