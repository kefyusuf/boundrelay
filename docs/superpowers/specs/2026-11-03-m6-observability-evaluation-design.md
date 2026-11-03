# M6 Observability, Evaluation, and Fault Injection Design

- **Date:** 2026-11-03
- **Status:** Proposed — awaiting owner review and written-design approval
- **Milestone:** M6 — Observability, evaluation, and fault injection
- **Project:** BoundRelay
- **Baseline:** merged M5 at `fa8ae49357eb16e2ac95352c1ad30278dc48b10f`
- **Decision:** [D-017](../../decisions/D-017-m6-observability-evaluation-faults.md), proposed
- **Depends on:** [foundation design](../../design/2026-09-02-foundation-design.md), D-001 through D-016, completed M0–M5 verification

## 1. Purpose and design brief

M6 is the first cross-cutting milestone: it introduces no new business scenario. The roadmap requires run/step/model/tool/handoff/checkpoint/approval event coverage, cost/latency/retry attribution, golden trajectories with behavioral probes, regression evaluation, and a failure matrix with chaos-style exercises.

Lessons 00–05 already emit the full event surface the foundation declares for the implemented scope. M6 makes that surface measurable and evaluable: deterministic attribution on every run result, language-agnostic golden trajectories for all canonical cases, a standalone regression evaluator, a machine-readable failure matrix whose every row is proven by an executed probe, and deterministic fault-injection exercises that replay declared faults on demand.

This proposed design preserves offline execution, TypeScript/Python parity, lesson-local implementations, and exact-revision evidence. All attribution is fixture-priced and clock-injected — no real metrics backend, no wall-clock dependence.

The teaching objective is:

> If you cannot evaluate behavior against recorded expectations and prove every declared failure's response on demand, you do not have observability — you have logs. Attribution, goldens, and the failure matrix turn logs into evidence.

## 2. Approaches considered

| Approach | Benefit | Limit | Choice |
|---|---|---|---|
| Cross-cutting evaluation layer: attribution on results, goldens per case, evaluator, failure matrix | Measures the real surface; regression evidence spans all six lessons | No new business behavior to teach | Recommended |
| A new synthetic lesson dedicated to observability | Follows the lesson rhythm | Observability is not a business scenario; a synthetic scenario would teach fake events | Rejected |
| OpenTelemetry or a real metrics backend | Industry surface | Network, dependency, nondeterminism; violates D-006/D-008 | Rejected |

### Teaching sequence

Follow D-005: measure what exists (attribute cost/latency/attempts to steps), record golden trajectories, evaluate a fresh run against them, inject a regression (a deliberate behavior change in a fixture) and watch the evaluator fail, then exercise the failure matrix — replaying every declared fault and asserting its mapped response. The lesson explains why wall-clock latency is never evidence and why goldens are normalized projections, not raw traces.

## 3. Event surface completion and attribution

The shared event envelope stays at version `1.0`; no new event types are introduced. M6 audits the implemented surface: every lesson's canonical cases must emit exactly the event types its design declares, with payload key-exactness already enforced by the M0–M5 gates. The audit is a contract test (`test_m6_contracts.py`) mapping each of the 38 canonical cases to its expected event-type set; drift fails closed.

Attribution extends every lesson's run result with a closed, deterministic block:

```json
"attribution": {
  "steps": [
    {"step_name": "worker.order-details", "latency_ms": 12, "cost_cents": 0, "attempts": 1}
  ],
  "totals": {"latency_ms": 40, "cost_cents": 9, "attempts": 4}
}
```

- **Latency** comes from an injected deterministic clock: each lesson's scenario fixture gains fixed per-step `latency_ms` values; the runner sums them per step. Wall-clock time is never recorded and never compared.
- **Cost** comes from a fixture price table: model decisions, tool calls, effect submissions, and handoffs have fixed `cost_cents` per scenario. Reads cost zero; M1's model steps and M5's effect carry canonical prices.
- **Attempts** count real invocations per step across phases (M4 resume re-execution, M5 reconciliation), reconciled into one record per step name.

Attribution is part of the run result (schema-validated, parity-compared) — not new events. The foundation's `budget.consumed` event stays unimplemented; it belongs to a future milestone with real budget enforcement.

## 4. Golden trajectories

For every canonical case across lessons 00–05 (7 + 8 + 5 + 6 + 6 + 6 = 38), a golden trajectory is recorded under `fixtures/goldens/<scenario>/<case>.json`:

- the normalized business result (the gate's existing business projection);
- the normalized event-type sequence (ordered list of `{type, step_name}` with generated identifiers and timestamps removed);
- the attribution block.

Goldens are language-agnostic: both implementations must produce the same normalized projection. They are recorded once per accepted behavior change via a regeneration command (`python tools/evaluate.py --regenerate <scenario> <case>`) that requires a clean worktree and writes a diff visible in review. A golden is evidence, not a snapshot of convenience; regeneration is a reviewed action, never a side effect of evaluation.

## 5. Regression evaluation

`python tools/evaluate.py` is the standalone evaluator:

1. Discovers all canonical cases from the six scenario fixtures.
2. Runs each case through both language CLIs with offline guards (reusing the gates' subprocess discipline).
3. Normalizes results and event sequences; compares against goldens.
4. Validates attribution completeness (every executed step attributed; totals equal the sum).
5. Emits `evaluation-report.json`: per-case PASS/FAIL with the first divergent field on failure.

The evaluator is fail-closed: a missing golden, a missing language run, or an unexplained divergence is a tooling error. It is deliberately independent of the per-milestone gates — the gates prove per-lesson contracts; the evaluator proves cross-lesson regression behavior and is invoked by the M6 authority on top of the M5 chain.

## 6. Failure matrix and fault-injection exercises

`fixtures/failure-matrix.yaml` is a machine-readable table; every row maps a declared failure class to its canonical proof:

| Column | Meaning |
|---|---|
| `failure_id` | `M0-F1` … `M5-Fn`, stable identifiers |
| `lesson`, `fault` | the scripted fault (invalid route, unknown tool, malformed handoff, crash windows, corrupt state, rejected approval, sink unavailable, …) |
| `expected_response` | status, failure code, exit code, zero-invocation claims |
| `proof` | the test/probe identity that asserts the response (must exist and pass) |

Chaos-style exercises are deterministic: a harness (`tools/chaos.py`) replays selected fault injections against the lessons' existing scripted controls — no new fault machinery is built. The exercises prove the matrix live: each row's fault is injected, the run executes, and the observed response must equal the row's `expected_response`. The matrix coverage test fails if any declared failure class lacks a row, or any row's proof identity is absent from the language suites.

## 7. Canonical evaluation set and authority

M6 adds no new CLI cases. Its evaluation set is the 38 existing cases (both languages) plus the full failure matrix. The documented authority is `python scripts/verify_m6.py`: it captures a clean starting revision, invokes `python scripts/verify_m5.py` once (the M5→M0 chain), then runs the contract audit, the evaluator over all 38 cases, the chaos exercises over the failure matrix, and the verifier-safety suite (normal and `python -O`), publishing `.boundrelay/m6/verification-evidence.json` only for an unchanged HEAD. CI uploads `m6-verification-<revision>`.

## 8. Planned artifacts and architecture

- `contracts/observability/attribution.schema.json` (closed attribution block; referenced by result-schema updates per lesson);
- result-schema extensions for lessons 00–05 (+ `attribution`), fixture price/latency tables per scenario, injected deterministic clocks per lesson runtime;
- `fixtures/goldens/<scenario>/<case>.json` (38 goldens), `fixtures/failure-matrix.yaml`;
- `tools/evaluate.py`, `tools/chaos.py`, `tools/contracts/test_m6_contracts.py`, `tools/parity/{verify_m6,test_m6_verification_safety}.py`, `scripts/verify_m6.py`, `.github/workflows/m6.yml`;
- `docs/observability.md` (attribution semantics) and `lessons/`-level README updates; no new lesson directory — M6's teaching content lives in `docs/` and the evaluator's own walkthrough.

No new runtime dependency. Result schemas change only by adding the attribution block (required) — a shared-contract change recorded as the plan's first ruling if normalization details need refinement.

## 9. Invariants and completion criteria

1. Every canonical case's event-type sequence matches its declared surface — audited, fail-closed.
2. Attribution is present on every run result; totals equal the per-step sum.
3. Latency is clock-injected and deterministic; wall-clock never enters evidence.
4. Cost is fixture-priced; prices are visible in the scenario fixtures.
5. Attempts reconcile multi-phase invocations into one record per step.
6. All 38 cases have goldens; both languages match them.
7. Golden regeneration requires a clean worktree and produces review-visible diffs.
8. The evaluator is fail-closed on missing/divergent evidence.
9. Every declared failure class has a matrix row and a passing proof identity.
10. Chaos exercises replay each fault live and match the matrix response.
11. No raw payloads, prompts, or private values enter attribution or goldens.
12. M0–M5 gates remain valid; all M6 evidence is bound to the current candidate revision.

(Invariants 13–20 are completed at plan time, mapping to the implementation tasks.)

## 10. Explicit exclusions

M6 does not introduce real metrics backends, OpenTelemetry, dashboards, trace inspectors (the v1.0 exit-criteria inspector remains future), real cost APIs, wall-clock SLOs, random chaos, destructive fault injection, new business scenarios, model-backed evaluation, Go, MCP, framework mappings, or shared-runtime extraction.

## 11. Written-design review gate

This design is **Proposed**. The owner's written-design approval — covering the attribution contract, golden mechanics, the evaluator's independence, the failure matrix, and the chaos-harness scope — is required before the implementation plan is drafted. Design acceptance alone does not authorize product implementation.

