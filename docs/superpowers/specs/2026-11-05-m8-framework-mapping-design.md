# M8 Framework Mapping Design (LangGraph × M3)

- **Date:** 2026-11-05
- **Status:** Accepted by the owner on 2026-11-05; implementation planning follows
- **Milestone:** M8 — Framework mappings
- **Project:** BoundRelay
- **Baseline:** merged M7 at `ee2d2e9d80a086ea2e1862dab1babc0ce13225f0`
- **Decision:** [D-019](../../decisions/D-019-m8-langgraph-m3-mapping.md), proposed
- **Depends on:** [foundation design](../../design/2026-09-02-foundation-design.md), D-001 through D-018, [D-008](../../decisions/D-008-framework-policy.md), completed M0–M7 verification

## 1. Purpose and design brief

M8 adds the first framework mapping per D-008: frameworks enter only after the first-principles pattern is taught, and every mapping must document **what the framework provides, what remains application responsibility, what becomes hidden, and how to exit the abstraction**.

This proposed design pins M8 to one vertical slice: **LangGraph (Python) × the M3 `order-brief` fan-out/fan-in lesson**. LangGraph is the mapping target because its graph-of-nodes model is the closest published analogue to M3's orchestrator pattern, and because its feature set (state channels, parallel dispatch, built-in checkpointing) collides instructively with M3's invariants — the collision is the teaching content.

The mapping is a **separate, non-authoritative artifact**: it never feeds the goldens, the failure matrix, or the M0–M7 gates. The canonical lessons remain the source of truth; the mapping exists to expose what a framework buys, hides, and costs.

The teaching objective is:

> Rebuild the M3 run on LangGraph and observe three things: which invariants come for free, which must be re-implemented inside the framework anyway, and which the framework silently changes. The canonical lesson remains the exit path.

## 2. Approaches considered

| Approach | Benefit | Limit | Choice |
|---|---|---|---|
| LangGraph × M3 (Python) | Direct analogue of the orchestrator pattern; parallel dispatch and state channels collide instructively with M3's invariants; Python matches the most lesson sources | Adds the repo's first framework dependency | Recommended |
| OpenAI Agents SDK × M0/M1 | Maps to agent-loop teaching | M1's tool loop already models the SDK's shape closely — less instructive collision | Defer |
| All five candidate frameworks at once | Completes the roadmap list | Five dependency surfaces, five parity matrices, unreviewable | Rejected |
| LangGraph × M4 | Shows built-in checkpointing | M4's durable-state invariants are richer than the framework's; collision content overlaps M3's | Defer |

### Teaching sequence

Follow D-005: run the canonical M3 flows (TS/PY goldens), rebuild them as a LangGraph graph, run the six cases through the mapping, and record — per invariant — kept / re-implemented / silently changed / absent. The naive version trusts the framework's defaults (uncapped parallel dispatch, framework-chosen failure propagation); the corrected version re-establishes M3's failure taxonomy and canonical ordering inside the graph. The lesson README answers D-008's four questions explicitly.

## 3. Mapping artifact and dependency isolation

The mapping lives at `mappings/langgraph-m3/python/` with its **own** package (`boundrelay-m3-langgraph`) and **own** pinned `requirements-dev.txt` (LangGraph version pinned exactly, installed in its own venv space via the documented commands). Isolation rules:

- The mapping is the **first third-party runtime dependency** in the repository; no lesson, contract, gate, evaluator, or Go module may import it. A dependency-isolation test (`tools/contracts/test_m8_contracts.py`) proves: the M0–M5 lesson sources, the gates, the evaluator, and `go/` contain zero references to the mapping's package or `langgraph`.
- The mapping reads the same M3 fixtures (scenario + worker projections already exist as JSON) and the same closed result schema. It emits its own trace format (LangGraph's native stream) — explicitly **not** the shared envelope; trace parity is out of scope and that exclusion is part of the teaching.
- Offline determinism holds: graph nodes are the same deterministic scripted workers; no LLM calls; no network. The pinned dependency is installed at setup time (like npm ci), never at run time.

## 4. Parity boundary: business results, not traces

The mapping must reproduce, for all six canonical M3 cases, results that satisfy the **M3 result schema** with business projections equal to the TS/PY/Go goldens: `order_id`, `status`, `worker_outcomes` (closed shapes, canonical order), `synthesis_invoked`, `brief`, `failure_code`, and attribution assembled from the same fixture tables (the mapping computes its own attribution — same tables, same rules).

Explicitly **not** parity-bound: `run_id`/trace-path plumbing, event sequences, `peak_concurrency` semantics (LangGraph's dispatcher may exhibit different admission timing — the mapping documents whatever the framework produces and the result's value is recorded, not normalized), and the shared event envelope.

The six cases are re-asserted through the mapping: three-success → `SUCCEEDED`/complete brief; declared failure and invalid output → `PARTIAL` with exact missing-worker order; all-failed → `FAILED`/`ALL_WORKERS_FAILED`, no synthesis; completion-order independence of the brief.

## 5. The four D-008 questions (the mapping's required findings)

The mapping's README must answer, with executable proof:

1. **What the framework provides:** graph topology, parallel branch dispatch, state reduction, optional built-in checkpointing, native streaming/trace format.
2. **What remains application responsibility:** the M3 failure taxonomy (`WORKER_EXECUTION_FAILED` vs `INVALID_WORKER_OUTPUT`), outcome validation before publication, canonical ordering of outcomes and brief sections, attribution assembly, the bounded-admission invariant.
3. **What becomes hidden or changes:** the framework's own execution telemetry replaces the shared envelope; admission timing (and therefore `peak_concurrency`) is framework-chosen; default error propagation must be overridden node-by-node to preserve the taxonomy; built-in checkpointing, if enabled, uses framework-owned state formats (the M4 lesson's counterpoint).
4. **How to exit:** the mapping imports the canonical fixtures and schemas only through their checked-in artifacts; deleting `mappings/` leaves every lesson, gate, golden, and evidence path intact (proven by the isolation test).

The bounded-admission finding is the centerpiece: LangGraph's parallel dispatch does not expose M3's 1/2-slot semaphore invariant as a first-class primitive; the mapping demonstrates what it takes to re-establish the cap inside the framework (per-node executor wrapping) versus what the framework leaves uncapped by default — and the naive version demonstrates the uncapped behavior honestly.

## 6. Verification authority and evidence

`python scripts/verify_m8.py` — clean starting revision → invoke `verify_m7.py` once (the M7→M0 chain) → mapping suite (`go`-free, unittest): fixture loading, six parity cases, dependency isolation, D-008 four-question assertions → publish `.boundrelay/m8/verification-evidence.json` on an unchanged HEAD. CI: `.github/workflows/m8.yml` installs the pinned LangGraph dependency in the mapping space and runs the same authority.

The mapping suite is fast and self-contained (no `go` gates beyond the chained M6/M7 flow inside verify_m7).

## 7. Invariants and completion criteria

1. The mapping reproduces all six M3 business projections within the M3 result schema.
2. Failure taxonomy preserved node-by-node; a naive-mode regression demonstrates default propagation failing the taxonomy.
3. Dependency isolation proven: zero `langgraph` references outside `mappings/langgraph-m3/`.
4. Attribution computed from the same fixture tables; totals = sum.
5. The mapping never mutates lessons, contracts, gates, goldens, or the evaluator.
6. D-008's four questions answered in the mapping README with executable proof.
7. M0–M7 gates remain valid; M8 evidence is bound to the current candidate revision.
8. The pinned LangGraph version is exact; installation is documented and offline-safe at run time.

(Invariants 9–16 are completed at plan time, mapping to implementation tasks.)

## 8. Explicit exclusions

M8 does not map additional frameworks (OpenAI Agents SDK, Google ADK, Mastra, Eino — separate later decisions), does not map other lessons, does not adopt LangGraph checkpointing as M4 semantics, does not introduce LLM calls or network use, does not touch the goldens/failure matrix, does not add framework dependencies outside `mappings/`, and does not introduce Go framework mappings (Eino) before the Go lessons themselves expand.

## 9. Written-design review gate

The owner approved this written design and D-019 on 2026-11-05, covering the single-mapping scope, the dependency-isolation policy, the business-result-only parity boundary, and the D-008 four-question deliverable.

The implementation plan is the next review artifact. Review that plan and select its execution method before product implementation. Design acceptance alone does not authorize product implementation.

