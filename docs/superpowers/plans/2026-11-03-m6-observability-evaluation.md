# M6 Observability, Evaluation, and Fault Injection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The owner selected Native execution on 2026-11-03.

**Goal:** Deliver the cross-cutting M6 layer: deterministic attribution on every lesson's run results, language-agnostic golden trajectories for all 38 canonical cases, an independent fail-closed regression evaluator, a machine-readable failure matrix proven live by deterministic chaos exercises, and exact-revision evidence chaining M5→M0.

**Architecture:** Attribution is result-level (no new events): an injected deterministic clock plus fixture price tables are wired into each lesson's existing runner; a contract audit pins every case's event-type surface; `tools/evaluate.py` runs all cases through both CLIs and compares normalized projections against `fixtures/goldens/`; `fixtures/failure-matrix.yaml` plus `tools/chaos.py` replay every declared fault through the lessons' existing scripted controls. One M6 authority owns the M5→M0 chain plus the evaluator, matrix, and safety suite.

**Tech Stack:** Node.js >=24, Python >=3.14, TypeScript strict ESM, Vitest, tsx, Ajv/ajv-formats, PyYAML, jsonschema, unittest. No new dependency.

**Spec:** [Accepted M6 design](../specs/2026-11-03-m6-observability-evaluation-design.md), [D-017](../../decisions/D-017-m6-observability-evaluation-faults.md), accepted 2026-11-03.

**Status:** Written design and implementation plan accepted on 2026-11-03. The owner selected Native execution; implementation proceeds on the feature branch. Exact-revision certification, independent review, CI, merge, and release remain separate observed states; consult PR evidence for their current status.

## Global Constraints

- No new event types; envelope stays `1.0`. Attribution lives on run results only.
- Attribution block (all six lessons, required): `{"attribution":{"steps":[{"step_name","latency_ms","cost_cents","attempts"}],"totals":{"latency_ms","cost_cents","attempts"}}}` — steps sorted by first appearance in the case's canonical step order; totals equal the per-step sum; attempts reconcile multi-phase invocations into one record per step name.
- `latency_ms` comes from per-step fixture values (`attribution.latency_ms` per step in each scenario fixture); wall-clock is never recorded or compared.
- `cost_cents` comes from a per-scenario `attribution.price_table` mapping step kinds to fixed prices (read=0, model decision/tool call/effect per fixture); every executed step's price is visible in its scenario fixture.
- Result schemas for lessons 00–05 gain the required `attribution` block (the only shared-contract change); lower gates are updated where they pin result payload keys.
- The event-surface audit maps each of the 38 canonical cases (M0:7, M1:8, M2:5, M3:6, M4:6, M5:6) to its exact expected event-type set; drift fails closed.
- Goldens live at `fixtures/goldens/<scenario>/<case>.json` with `{scenario_id, case_id, languages:['typescript','python'], result_projection, event_sequence:[{type, step_name}...], attribution}` — language-agnostic; both CLIs must produce the identical normalized projection.
- `tools/evaluate.py` runs every case through both CLIs offline, compares against goldens, validates attribution completeness, and writes `evaluation-report.json`; missing/divergent evidence is a tooling error. `--regenerate <scenario> <case>` requires a clean worktree and shows a diff.
- `fixtures/failure-matrix.yaml` rows: `{failure_id (M0-F1…M5-Fn), lesson, fault, expected_response:{status, failure_code, exit_code, invocations}, proof (test identity)}`; `tools/chaos.py` replays each fault via existing scripted controls and asserts the observed response equals the row; coverage tests fail on missing rows/absent proofs.
- Stay offline and framework-free; no metrics backend, no wall-clock SLOs, no random chaos. Exclude everything in the design's exclusions.
- Publish evidence only on a clean unchanged candidate revision, after M5 (and its lower chain) pass on that same revision. Safety checks must survive `python -O`.

## Review Focus

| Failure/input class | Required evidence | Owner |
|---|---|---|
| Attribution missing, totals ≠ sum, or wall-clock leaking into evidence | Schema rejection tests + deterministic-clock probes | Task 2 |
| Event surface drift (a case emitting an undeclared event type or losing a declared one) | Contract audit over all 38 cases, fail-closed | Task 1 |
| Golden drift accepted, or regeneration silently rewriting evidence | Golden comparison tests + clean-worktree regenerate guard | Tasks 3–4 |
| Evaluator passes with missing language run or missing golden | Fail-closed evaluator probes | Task 4 |
| Matrix row without proof, or chaos replay mismatching the row | Coverage tests + live replay assertions | Task 5 |
| Certification without the full evaluation set or matrix | Gate composition checks: 38 cases × 2 languages + all rows | Task 6 |

## File and Interface Map

| Files | Responsibility |
|---|---|
| `contracts/observability/attribution.schema.json` | Closed attribution block |
| `fixtures/scenarios/*.yaml` (+`attribution` tables), `fixtures/goldens/<scenario>/<case>.json`, `fixtures/failure-matrix.yaml` | Price/latency tables, goldens, matrix |
| `lessons/*/…` runners + result schemas (all six lessons) | Clock injection, price wiring, attribution assembly |
| `tools/evaluate.py`, `tools/chaos.py` | Regression evaluator, fault-replay harness |
| `tools/contracts/test_m6_contracts.py`, `tools/parity/{verify_m6,test_m6_verification_safety}.py`, `scripts/verify_m6.py`, `.github/workflows/m6.yml` | Audit, gate, safety, CI |
| `docs/observability.md`, root `README.md`, `.ai/delivery/current-scope.md` | Attribution semantics, teaching, scope |

### Stable Interfaces

- `Attribution`/`attribution`: exactly the block in Global Constraints. `buildAttribution(steps, priceTable, latencyTable)` / `build_attribution(...)` — pure, deterministic; rejects unknown step names or missing table entries.
- Scenario fixtures gain `attribution: {latency_ms: {<step_name>: int}, price_table: {<kind>: int}}`; step kinds: `read`, `model_decision`, `tool_call`, `effect`, `handoff`, `route`, `synthesis` (0 where not applicable).
- `tools/evaluate.py`: `--scenario <id> --case <id>` (single), `--all`, `--regenerate <scenario> <case>` (clean-worktree required), `--report <path>`; exit 0 only when every requested case passes in both languages.
- `tools/chaos.py`: `--all` or `--failure-id <id>`; loads the matrix, injects each fault via the lesson's scripted controls, asserts `expected_response`; exit 0 only when all selected rows pass.
- `EXPECTED_EVENT_SURFACE` in `tools/contracts/test_m6_contracts.py`: `{scenario_id: {case_id: [event types...]}}` — the audit's authoritative map.

### Canonical Evaluation Set

No new CLI cases. The set is the existing 38 canonical cases across lessons 00–05, each run in both languages, plus the complete failure matrix (rows per lesson: M0 invalid route; M1 unknown tool/malformed arguments/timeout/tool failure; M2 context loss/unavailable receiver/low-confidence fallback; M3 declared failure/invalid output/all-failed/unexpected-drain; M4 crash windows/cancel/corrupt state/binding mismatch; M5 approval rejection/submit-window crash/sink unavailable/duplicate key).

## Commands and Working Directory

Use repository root as explicit cwd; `.venv/Scripts/python.exe` on this host. A RED step must fail on its named behavioral assertion, not missing packages. After each task's GREEN steps, run affected tests + TS typecheck, stage only its files, commit with the specified message. Run the complete clean-revision authority after Task 7; intermediate checks do not certify M6.

## Task 1: Attribution Contracts, Fixture Tables, and Event-Surface Audit

**Files — Create:** `contracts/observability/attribution.schema.json`, `tools/contracts/test_m6_contracts.py`, `docs/observability.md`. **Modify:** all six `fixtures/scenarios/*.yaml` (+`attribution` tables).

**Interfaces:** Closed attribution schema (draft 2020-12). Scenario tables: `attribution.latency_ms` per step name and `attribution.price_table` per step kind; prices visible per fixture; reads cost 0. The audit map covers all 38 cases with exact event-type sequences derived from each lesson's accepted design.

- [ ] Write `test_attribution_schema_and_tables` (schema closes; tables parse; every canonical step name across the six scenarios has a latency and a price kind; reads price 0) and `test_event_surface_audit` (EXPECTED_EVENT_SURFACE covers 38 cases in 6 scenarios; each case's declared types match its lesson design; unknown scenario/case fails).
- [ ] Run `python -m unittest tools.contracts.test_m6_contracts -v`; expect RED on missing schema/tables/audit.
- [ ] Implement the schema, the six fixture tables, the audit map, and `docs/observability.md` (attribution semantics, clock-injection rationale, golden mechanics).
- [ ] Rerun; expect PASS. Commit only Task 1 files: `feat: define M6 attribution contracts and observability audit`.

## Task 2: Deterministic Attribution in All Six Lessons

**Files — Modify:** each lesson's runner (TS+PY) to wire the injected clock + price table and assemble attribution into the run result; each lesson's result schema (+ required `attribution`); lower-gate payload-key updates where they pin result shapes; per-lesson tests.

**Interfaces:** `buildAttribution` implemented per lesson (idiomatic mirrors); runners add it before result validation; multi-phase lessons (M4/M5) reconcile attempts across phases into the final result.

- [ ] Paired per-lesson tests: attribution present and schema-valid on every canonical result; totals equal sum; latency values equal the fixture table; attempts equal 1 on single-phase cases.
- [ ] Paired M4/M5 multi-phase tests: crash-resume and submit-window-resolved results show reconciled attempts (re-executed/reconciled steps counted once per real invocation across phases) and summed latencies.
- [ ] Paired negative tests: result without attribution rejected by schema; unknown step name in the table rejected by buildAttribution.
- [ ] Update lower gates' result payload expectations (additive only). All six lesson suites + typecheck GREEN; lower gates rerun green (verify_m3 at minimum).
- [ ] Commit: `feat: attribute M0-M5 runs with deterministic cost and latency`.

## Task 3: Evaluator Core and Goldens for Lessons 00–02

**Files — Create:** `tools/evaluate.py`, `fixtures/goldens/{support-triage,order-investigation,support-handoff}/<case>.json`, `tools/parity/test_m6_evaluation.py` (evaluator safety tests).

**Interfaces:** The evaluator discovers cases from scenario fixtures, runs both CLIs (offline guards, subprocess discipline as the gates), normalizes (business projection + event-type sequence + attribution), and compares against goldens. `--regenerate` requires a clean worktree. Fail-closed on missing golden/language run.

- [ ] Write evaluator tests: missing golden → tooling error; single-language result missing → tooling error; language mismatch → tooling error; regenerate without clean worktree → refused; report shape on success/failure.
- [ ] RED → implement evaluator core → GREEN.
- [ ] Record goldens for lessons 00–02 cases (20) via the regenerate command on a clean worktree; diff-review them.
- [ ] Run the evaluator over lessons 00–02; expect all PASS in both languages. Commit: `feat: add M6 evaluator with golden trajectories for early lessons`.

## Task 4: Golden Coverage Completed and Evaluation Reporting

**Files — Create:** `fixtures/goldens/{order-brief,order-brief-recovery,order-closure}/<case>.json`. **Modify:** `tools/evaluate.py` (attribution-completeness validation, `evaluation-report.json` totals).

- [ ] Record goldens for lessons 03–05 (18 cases) on a clean worktree.
- [ ] Paired attribution-completeness tests: a result whose step lacks attribution, or whose totals ≠ sum, fails the evaluator.
- [ ] Run `python tools/evaluate.py --all`; expect 38/38 PASS ×2 languages and a complete report. Commit: `feat: complete M6 golden coverage and evaluation reporting`.

## Task 5: Failure Matrix and Chaos Exercises

**Files — Create:** `fixtures/failure-matrix.yaml`, `tools/chaos.py`, matrix coverage tests in `tools/parity/test_m6_evaluation.py`.

**Interfaces:** Rows carry stable `failure_id`s, the lesson's scripted fault, `expected_response` (status/failure_code/exit/invocations), and the exact proof test identity. The harness replays faults via existing controls only.

- [ ] Write the matrix (~20 rows across six lessons); coverage test: every declared failure class has a row; every row's proof identity exists in the language suites.
- [ ] Paired chaos tests: replay each row live; observed response must equal `expected_response` (assert status, code, exit, invocation claims).
- [ ] Run `python tools/chaos.py --all`; expect all rows green. Commit: `feat: prove M6 failure matrix through deterministic chaos exercises`.

## Task 6: Raw-First Parity and Exact-Revision Verification Authority

**Files — Create:** `tools/parity/verify_m6.py`, `tools/parity/test_m6_verification_safety.py`, `scripts/verify_m6.py`.

**Interfaces:** Mirror the M5 gate: clear `.boundrelay/m6` → clean worktree + starting SHA → invoke `scripts/verify_m5.py` once → validate M5 evidence SHA+PASSED → contracts audit → evaluator over all 38 cases ×2 languages → chaos over the full matrix → verifier-safety suite (normal + `python -O`) → normalized golden/report comparisons → recheck clean HEAD → publish `.boundrelay/m6/verification-evidence.json`.

- [ ] Safety suite: mutation tests (attribution tampering, totals drift, golden accepted-divergence, matrix row without proof, chaos response mismatch, report tampering) fail before certification; publication checks survive `python -O`; probe identities required from the evaluator/chaos suites.
- [ ] RED → implement → GREEN. Full authority deferred to Task 7.
- [ ] Commit: `test: certify M6 evaluation parity and fault evidence`.

## Task 7: Documentation, CI, and Candidate Certification

**Files — Modify/Create:** root `README.md` (M6 status + verify section), `.ai/delivery/current-scope.md`, `.github/workflows/m6.yml`, this plan's ledger.

- [ ] README: M6 status paragraph + `Verify M6 locally` section (evaluator/matrix usage). Scope: active phase M6, authority `verify_m6.py`, artifact `m6-verification-<revision>`.
- [ ] Exact-head M6 workflow (current action versions, `persist-credentials:false`, PR/main triggers, hidden evidence upload).
- [ ] Inspect scope/diff, `git diff --check`, commit: `docs: teach M6 observability and enable revision bound CI`. Do not change M0–M5 domain code beyond attribution wiring already landed.
- [ ] On the clean committed candidate run `python scripts/verify_m6.py`; expect PASSED on the exact SHA with the M5 chain PASSED, 38×2 evaluation PASS, full matrix green, safety suite green. Rerun after any fix on the new clean revision.
- [ ] Fresh whole-branch review; resolve material findings in scope; rerun affected checks + full authority when evidence is invalidated.
- [ ] Push/update the PR; check M0–M6 CI on the exact head; verify the downloaded artifact. Merge/release require the owner's separate authorization.
- [ ] Append the activity entry and update continuation state.

## Inline Self-Review and Coverage

Tasks 1–2 fix attribution contracts/tables and runtime wiring; Task 3–4 own the evaluator and goldens; Task 5 owns the matrix and chaos; Task 6 owns evidence; Task 7 owns teaching/CI/certification. All six Review Focus rows have named tests. The plan specifies behavior, not implementation bodies. Future-file paths are planned artifacts.

| Design invariants | Implementation and evidence |
|---|---|
| 1–5 (surface audit + attribution) | Tasks 1–2 |
| 6–8 (goldens + evaluator) | Tasks 3–4 |
| 9–10 (matrix + chaos) | Task 5 |
| 11 (privacy) | Tasks 1–4 (projection allowlists) |
| 12 (chain + revision evidence) | Task 6 |

## Execution Ledger

- **Ruling 5 (2026-11-03, Task 1/2):** Step-name and audit-key conventions are fixed. The event-surface audit keys M0 as `<case_id>@<mode>` (seven canonical case/mode combinations); other scenarios key by case id. Attribution step names: M0 `classify` + `specialist.<route>`; M1 `model` + `tool.<tool>` (M1/M2 emit no `step.*` events, so the loaders' tables fix the names); M2 `classify` + `receiver.<receiver>`; M3/M4 `worker.<id>` + `synthesize`; M5 `worker.<id>` + `effect.submit`. Per-step latency = fixture table × attempts; step cost = fixture price × attempts by kind. M4 crash controls fire after the worker's outcome is recorded, so canonical multi-phase runs never restore a RUNNING worker and every recorded worker counts attempts 1 (crash-resume p2 = [1,1,1]); the restored-RUNNING ×2 rule stays implemented for any future genuinely re-executed worker. M5 counts the invocation of record: workers 1 each, `effect.submit` 1 when an effect of record exists (landed or adopted — adoption counts the original attempt), and a rejected approval omits the effect step record entirely (totals span executed steps only). Result schemas embed the canonical attribution block inline (kept self-contained, no cross-file `$ref`); the six loaders accept the tables optionally and each runner fails closed when they are missing.

## Execution Handoff

The owner approved this written plan and selected **Native** on 2026-11-03: implement the seven tasks in this session using `superpowers:executing-plans`, then obtain one fresh whole-branch review. Keep implementation within the accepted design and record any necessary ruling in the plan's execution ledger.



