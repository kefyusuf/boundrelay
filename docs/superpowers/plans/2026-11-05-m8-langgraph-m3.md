# M8 LangGraph × M3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The owner selected Native execution on 2026-11-05.

**Goal:** Deliver the single LangGraph (Python) × M3 mapping: a non-authoritative artifact under `mappings/langgraph-m3/` with an exactly-pinned LangGraph dependency, business-result parity for all six M3 cases, dependency isolation proven, D-008's four questions answered with executable proof, and an M8 authority chaining M7→M0 plus the mapping suite.

**Architecture:** The mapping package reads the canonical M3 fixture projections (`fixtures/goprojections/order-brief/{scenario,workers}.json`) and the closed result schema shapes; builds a naive (uncapped, default-propagation) and a corrected (taxonomy-preserving, canonically ordered) LangGraph graph; assembles attribution from the same fixture tables; and asserts business projections against the M3 goldens' projections. The mapping suite is unittest-based and self-contained.

**Tech Stack:** Python >= 3.14, LangGraph (version pinned exactly in `mappings/langgraph-m3/python/requirements-dev.txt`), PyYAML/jsonschema already in the dev requirements. No other new dependency anywhere.

**Spec:** [Accepted M8 design](../specs/2026-11-05-m8-framework-mapping-design.md), [D-019](../../decisions/D-019-m8-langgraph-m3-mapping.md), accepted 2026-11-05.

**Status:** Written design and implementation plan accepted on 2026-11-05. The owner selected Native execution; implementation proceeds on the feature branch. Exact-revision certification, independent review, CI, merge, and release remain separate observed states; consult PR evidence for their current status.

**Implementation note:** the plan pins outcomes, not LangGraph API calls — the exact API usage (graph construction, parallel dispatch, state reducer, stream format) is resolved empirically in Task 2 after installing the pinned version.

## Global Constraints

- Dependency isolation: `langgraph` may only be imported under `mappings/langgraph-m3/`; zero references anywhere else (lessons, contracts, gates, evaluator, chaos, `go/`). Proven by a contracts test.
- The mapping is non-authoritative: it never mutates lessons, contracts, gates, goldens, the evaluator, or the failure matrix; it reads checked-in artifacts only (fixture projections + the M3 result schema shapes).
- Business-result parity: all six M3 case keys produce M3-schema-valid results whose business projections equal the M3 goldens' `result_projection` (status, worker_outcomes incl. canonical order and failure codes, synthesis_invoked, brief, failure_code); attribution assembled from the same fixture tables (totals = sum).
- Trace parity is out of scope: the mapping uses LangGraph's native stream; no shared-envelope claims.
- The naive graph (uncapped dispatch, default error propagation) is retained as the teaching regression: it demonstrates taxonomy violations and unbounded admission honestly, asserted as the naive behavior.
- Bounded admission in the corrected graph is re-established inside the framework (per the accepted design's centerpiece finding) and its cost documented.
- Offline: graph nodes are deterministic scripted workers; no LLM calls, no network at run time; the pinned dependency installs at setup only.
- Stay within D-008/D-019's scope: no other framework, no other lesson, no LangGraph-checkpointing-as-M4-semantics, no goldens/matrix changes.
- Publish evidence only on a clean unchanged candidate revision, after M7 (and its lower chain) pass on that same revision. Safety checks must survive `python -O`.

## Review Focus

| Failure/input class | Required evidence | Owner |
|---|---|---|
| Isolation breach (langgraph referenced outside mappings/) | Contracts isolation test, fail-closed | Task 1 |
| Taxonomy violation (invalid output treated as a fact; failure codes lost) | Six parity cases + naive-regression assertions | Tasks 2–3 |
| Business projection drift vs goldens | Three-way (TS golden vs mapping result) comparison per case | Task 4 |
| Four-question claims without executable proof | README assertions backed by tests | Task 5 |
| Mapping mutating canonical artifacts | Isolation test + gate composition | Task 6 |
| Certification without the chained lower evidence | verify_m8 composition checks + safety suite | Task 6 |

## File and Interface Map

| Files | Responsibility |
|---|---|
| `mappings/langgraph-m3/python/{pyproject.toml,requirements-dev.txt}` | Package + exactly-pinned LangGraph |
| `mappings/langgraph-m3/python/src/boundrelay_m3_langgraph/{fixtures.py,graph.py,naive.py,results.py,attribution.py,cli.py}` | Fixture loading, corrected graph, naive graph, result assembly, attribution, CLI |
| `mappings/langgraph-m3/python/tests/test_*.py` | Mapping suite |
| `mappings/langgraph-m3/README.md` | The D-008 four questions + exit path |
| `tools/contracts/test_m8_contracts.py` | Isolation + manifest + parity-key checks |
| `tools/parity/{verify_m8,test_m8_verification_safety}.py`, `scripts/verify_m8.py`, `.github/workflows/m8.yml` | Gate, safety, CI |
| root `README.md`, `.ai/delivery/current-scope.md` | Status, verify section |

### Stable Interfaces

- `fixtures.py`: load the goprojection scenario/workers JSON (strict), the attribution tables, and the M3 goldens' projections for comparison.
- `graph.py`: `build_corrected_graph()` — the taxonomy-preserving graph; `naive.py`: `build_naive_graph()` — uncapped dispatch with default propagation.
- `results.py`: assemble M3-schema-valid results (structural validation mirroring the closed schema).
- `attribution.py`: `build_attribution(step_records, tables)` mirroring M6's rules (per-step latency = table×attempts; totals = sum).
- `cli.py`: `--case <id> --trace <stream-file> [--mode naive|corrected]` — one JSON result line; naive mode allowed to diverge (teaching artifact).

## Task 1: Isolation Contracts and Mapping Scaffolding

**Files — Create:** `tools/contracts/test_m8_contracts.py`, `mappings/langgraph-m3/python/{pyproject.toml,requirements-dev.txt}`, package skeleton.

- [ ] Contracts test: no `langgraph` reference outside `mappings/langgraph-m3/` (scan lessons/, contracts/, tools/, scripts/, go/); mapping manifest (pyproject name `boundrelay-m3-langgraph`, requirements pin exact + single framework dep); six parity case keys enumerated.
- [ ] RED → scaffold (pyproject, pinned requirements — resolve the exact current LangGraph version empirically and pin it — package skeleton) → GREEN; install the pinned dep into a mapping-local venv space and prove import works.
- [ ] Commit: `feat: scaffold M8 LangGraph mapping with isolation contracts`.

## Task 2: Fixture Loading and the Corrected Graph

**Files — Create:** `src/boundrelay_m3_langgraph/{fixtures,graph,results}.py` + tests.

- [ ] Fixture loading (strict) from the goprojections; six cases; worker fixture map.
- [ ] Corrected graph: taxonomy-preserving failure handling (declared → WORKER_EXECUTION_FAILED, invalid → INVALID_WORKER_OUTPUT outcomes inside nodes), canonical outcome ordering, one synthesis node gated on >=1 success, uncapped-vs-capped dispatch demonstrated (the bounded wrapper documented; naive mode separated).
- [ ] Result assembly mirroring the closed M3 schema shape.
- [ ] RED → implement → GREEN. Commit: `feat: implement the corrected M3 LangGraph graph`.

## Task 3: Naive Graph, Attribution, and the Six Parity Cases

**Files — Create:** `src/boundrelay_m3_langgraph/{naive,attribution}.py`, `cli.py` + tests; `mappings/langgraph-m3/README.md`.

- [ ] Naive graph: uncapped dispatch + default propagation, asserted as the naive behavior (taxonomy violations + no cap) — the teaching regression.
- [ ] Attribution mirroring M6 rules from the same tables.
- [ ] Six parity cases: mapping results (corrected mode) business-projection-equal to the M3 goldens; naive mode asserted divergent where the framework defaults diverge.
- [ ] README: the four D-008 questions with pointers to the proving tests; exit path.
- [ ] RED → implement → GREEN. Commit: `feat: complete M8 mapping parity and D-008 findings`.

## Task 4: M8 Verification Authority

**Files — Create:** `tools/parity/verify_m8.py`, `tools/parity/test_m8_verification_safety.py`, `scripts/verify_m8.py`.

- [ ] Safety suite (mirror M7's): mapping mutating a canonical artifact blocks; isolation breach blocks; parity drift (a parity case failing) blocks publication; naive-mode divergence is expected, not a defect; stale evidence cleared first; moved HEAD/dirty tree refuse; survives `python -O`.
- [ ] `scripts/verify_m8.py`: clear `.boundrelay/m8` → clean SHA → `verify_m7.py` once → M7 evidence validated → contracts `test_m8_contracts` → mapping suite via ProofResult (mapping venv python) → publish `.boundrelay/m8/verification-evidence.json`. RED → implement → GREEN (full run deferred to Task 5).
- [ ] Commit: `test: certify M8 mapping parity and isolation evidence`.

## Task 5: Documentation, CI, and Candidate Certification

**Files — Modify/Create:** root `README.md` (M8 status + verify section), `.ai/delivery/current-scope.md`, `.github/workflows/m8.yml` (mapping venv setup + authority), plan ledger.

- [ ] README/scope updates; exact-head M8 workflow (installs the pinned LangGraph into the mapping venv; runs the authority).
- [ ] Commit: `docs: teach M8 mapping and enable revision bound CI`.
- [ ] On the clean committed candidate run `python scripts/verify_m8.py`; expect PASSED on the exact SHA (M7 chain + mapping suite). Rerun after any fix.
- [ ] Fresh whole-branch review; resolve findings in scope; push/update the PR; check M0–M8 CI on the exact head; merge/release require the owner's separate authorization.

## Inline Self-Review and Coverage

Tasks 1–3 build the isolated mapping with parity; Task 4 the authority; Task 5 teaching/CI/certification. All six Review Focus rows have named tests. The plan pins outcomes, not LangGraph API calls.

## Execution Handoff

The owner approved this written plan and selected **Native** on 2026-11-05: implement the five tasks in this session using `superpowers:executing-plans`, then obtain one fresh whole-branch review. Keep implementation within the accepted design and record any necessary ruling in the plan's execution ledger.


