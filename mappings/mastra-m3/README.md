# P5c Mapping — Mastra (TypeScript) × M3 `order-brief`

Non-authoritative framework mapping per [D-008](../../docs/decisions/D-008-framework-policy.md): the M3 bounded fan-out/fan-in lesson rebuilt on Mastra's workflow engine (`@mastra/core==1.82.0`) to expose what the framework buys, what must be re-implemented inside it anyway, what it silently changes, and how to leave. The mapping never feeds the goldens, the failure matrix, or the M0–M7 gates; it reads checked-in artifacts only (`fixtures/goprojections/order-brief/`, `fixtures/goldens/order-brief/`) and emits Mastra's native workflow stream — event-envelope trace parity is explicitly out of scope.

## Setup and run

The engine is pinned exactly (`typescript/package.json`: `"@mastra/core": "1.82.0"` with a committed lockfile; npm auto-installs its `zod` peer) and is installed at setup only. M3 has no model at all, and Mastra's workflow engine runs steps as plain functions: workflows with steps need no LLM, no API key, and no network — proven offline by `typescript/test/offline.test.ts`, which patches every network constructor (`net.connect`, `http.request`, `https.request`, `fetch`) to explode in a fresh child process before any import and then drives all six cases through the real engine.

```bash
# install into the mapping's own package (package.json + package-lock.json committed):
cd mappings/mastra-m3/typescript && npm ci
# suite (vitest, mirroring the M3 lesson's TypeScript tooling):
npm test
# one case through the workflow (one JSON result line on stdout; exit 0 domain, 2 tooling):
npx tsx src/cli.ts --case parallel-complete --trace .boundrelay/manual/p5c-native-stream.jsonl
# naive teaching mode (uncapped, default propagation; exits 2 by design):
npx tsx src/cli.ts --case parallel-partial-failure --mode naive --trace .boundrelay/manual/p5c-naive.jsonl
```

All six parity cases reproduce the M3 goldens' `result_projection` (status, canonical `worker_outcomes` with failure codes, `synthesis_invoked`, brief, `failure_code`, `peak_concurrency` 2/1, attribution totals 48/33) — proven by `typescript/test/parity.test.ts` (deep-equal minus `run_id`/`trace_path`, each published result validated against `contracts/results/order-brief-result.schema.json` with ajv, attribution deep-equal).

## D-008 question 1 — What the framework provides

The workflow graph itself (`createWorkflow` + `.then()`/`.parallel()`/`.branch()` composition committed once per run), the worker boundary as first-class Steps (`createStep` — the seam the three scripted workers plug into), parallel branch dispatch with per-step outputs keyed by step id (the fan-in's variable passing: the collect step reads `inputData['worker.<id>']`), a framework-native conditional (`branch` — the synthesis gate is a condition over the collected outcomes, so synthesis runs exactly once iff >=1 worker succeeded), the run machinery (`createRun`/`run.stream`), and the native stream (`workflow-start`, `workflow-step-start`, `workflow-step-result`, `workflow-finish` chunks with per-step payloads — written verbatim to `--trace`). The typed IO layer is Standard-Schema-based; the mapping deliberately runs identity passthrough schemas (dependency-free) because the closed M3 shapes are enforced by the mapping's structural validators, not by framework IO schemas.

Proof: `typescript/test/parity.test.ts` drives all six cases through the real engine and shows the native chunks (every `worker.*`, `collect`, `synthesize`, `finalize` step appears in the trace); the failed-worker test shows the engine recording the step as `success` with the mapped `failure_code` in its payload (taxonomy handled inside, not propagated); `test/offline.test.ts` proves the whole engine runs with every network constructor patched to explode.

## D-008 question 2 — What remains application responsibility

The whole M3 discipline: the scripted workers themselves (the fixture instructions are plain data; the mapping owns their interpretation), the M3 failure taxonomy inside each step (`mapping.workerOutcome`: declared error → `WORKER_EXECUTION_FAILED`, invalid return → `INVALID_WORKER_OUTPUT` via `results.validateWorkerOutput` — validated before publication; unexpected errors abandon the run and drain the executor), canonical ordering (structural: per-step outputs keyed by step id, merged in `WORKER_IDS` order by the collect step — `results.canonicalizeOutcomes` re-checks the fan-in), the fixture's completion-order semantics (completion-order release gates inside the executor — the framework has no notion of a scripted completion schedule), single synthesis ownership (the `synthesize` step is the only caller of `results.synthesizeBrief`, gated by the branch condition; the brief flows to finalize, so synthesis is invoked exactly once — unlike the LangGraph mapping, whose finalize recomputes the brief inside result assembly), attribution (`attribution.buildAttribution` from the same fixture tables, totals = sum, M6 rules), and the closed result shape itself (`results.validateResult` mirrors the checked-in schema by hand, including the totals = sum invariant that the JSON schema cannot express).

Proof: `typescript/test/taxonomy.test.ts` (declared failure → PARTIAL with exactly `["delivery-status"]` missing; invalid `UNKNOWN` output never published; all-failed → FAILED/`ALL_WORKERS_FAILED` with `synthesis_invoked` false and a null brief), `test/ordering.test.ts` (canonical order invariant under every feasible completion permutation; identical briefs; infeasible schedules trip the guard), `test/results.test.ts` (the structural validator rejects peak 3, published `MYSTERY` outputs, failed-without-code, and broken totals), `test/attribution.test.ts` (table × attempts, golden totals 48/33).

## D-008 question 3 — What becomes hidden or changes

**The bounded-admission cost (the centerpiece finding):** Mastra's `.parallel()` dispatches all branch steps at once and exposes no first-class 1/2-slot admission primitive for distinct worker branches. `.foreach({concurrency: N})` bounds homogeneous item streams, not three heterogeneous workers with per-worker completion gates. Re-establishing the cap therefore costs `mapping.BoundedWorkerExecutor` — canonical-order slot admission, completion-order release gates, a first-wave binding (the first release waits until `limit` workers have entered, proving the cap binds), a concurrency ledger — all application code running inside the worker steps while the engine still dispatches all three branches at once. The wrapper makes `peak_concurrency` deterministic (2 parallel / 1 sequential) at the price of owning admission in the app instead of the framework, plus a deadlock guard that fails the run fast instead of hanging.

Also rewritten by the framework: shared workflow **state is not a fan-in channel** — `setState` from parallel branches is last-write-wins (verified against 1.82.0: only the last writer's slot survives), so the fan-in rides on per-step outputs and a keyed merge instead. The **naive graph has no completion-order semantics at all**: with no gates, the parallel output arrives in step-definition order regardless of the fixture's scripted completion order (proven) — order control is app-owned. A failed run's **error is serialized to a plain `{message, name}` object**; the mapping recovers the original message from `.message`. Declared worker errors **propagate by default**: without the in-step taxonomy, one raise fails the whole run (the naive regression). The engine also logs step errors to its own console channel (visible in naive failures) and the native stream replaces the shared event envelope.

Proof: `typescript/test/admission.test.ts` (deterministic peaks 2/1; the cap-binding instrumentation; guard-tripped infeasible schedule; abandon-drains-waiters), `test/naive.test.ts` (3-way rendezvous records peak 3 vs the corrected 2; `UNKNOWN` published as a fact; declared error crashes the run with the trace prefix flushed; naive results fail the closed validator with null limit/attribution), `test/results.test.ts` and `test/parity.test.ts` (corrected runs match the goldens exactly).

## D-008 question 4 — How to exit the abstraction

The mapping imports the canonical fixtures, goldens, and schema shapes only through their checked-in artifacts (`fixtures.ts` reads `fixtures/goprojections/order-brief/` and `fixtures/goldens/order-brief/`; `test/parity.test.ts` validates against `contracts/results/order-brief-result.schema.json`). Nothing outside `mappings/mastra-m3/` references the package or `mastra`: `tools/contracts/test_p5c_contracts.py` fails closed on any `mastra`/mapping token under `lessons/`, `contracts/`, `tools/`, `scripts/`, `go/` outside a precise allowlist. Deleting `mappings/` leaves every lesson, gate, golden, and evidence path intact — the canonical lesson (`lessons/03-parallel-fanout-fanin/`) remains the source of truth and the exit path.

Proof: `tools/contracts/test_p5c_contracts.py` (isolation scan, manifest pin, parity keys) and `typescript/test/offline.test.ts` (every network constructor patched to explode; the engine completes all six case shapes anyway, with no API key and no model).

## Files

| File | Responsibility |
|---|---|
| `typescript/package.json` | Mapping package; single dependency `@mastra/core@1.82.0` (lockfile committed) |
| `typescript/tsconfig.json` | Strict settings matching the repo's lessons (`strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`) |
| `typescript/src/fixtures.ts` | Strict fixture/golden loading (checked-in artifacts only) |
| `typescript/src/results.ts` | M3-schema result assembly + structural validation (the closed shapes, hand-mirrored) |
| `typescript/src/attribution.ts` | Attribution from fixture tables (M6 rules) |
| `typescript/src/mapping.ts` | Mastra wiring: worker/collect/synthesize/finalize steps, `BoundedWorkerExecutor`, native-stream trace writer |
| `typescript/src/naive.ts` | Naive workflow (uncapped rendezvous, default propagation, unvalidated publication) |
| `typescript/src/cli.ts` | `--case/--mode/--trace`; exit 0 domain, 2 tooling |
| `typescript/test/` | Mapping suite (fixtures, results, attribution, parity, ordering, taxonomy, admission, naive, CLI, offline) |
