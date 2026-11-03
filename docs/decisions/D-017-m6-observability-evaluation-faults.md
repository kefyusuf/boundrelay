# D-017 — M6 Observability, Evaluation, and Fault Injection

- **Status:** Accepted
- **Date:** 2026-11-03

## Context

M5 is integrated and certified on main. Lessons 00–05 already emit the foundation's declared event surface for the implemented scope, and every milestone gate proves per-lesson contracts. The roadmap's next milestone concerns cost/latency/retry attribution, golden trajectories with behavioral probes, regression evaluation, and a failure matrix with chaos-style exercises. M0–M5 deliberately deferred cross-cutting observability and evaluation to this milestone.

M6 should make the existing surface measurable without adding a business scenario, real metrics infrastructure, or nondeterminism.

## Decision

Make M6 a cross-cutting evaluation layer over lessons 00–05:

- **Attribution:** every run result gains a closed, deterministic `attribution` block (per-step `latency_ms` from an injected deterministic clock, `cost_cents` from fixture price tables, `attempts` reconciled across phases). No new event types; the envelope stays at `1.0`.
- **Golden trajectories:** one language-agnostic normalized golden per canonical case (38 total) under `fixtures/goldens/`, covering the business projection, the event-type sequence, and attribution. Regeneration is a reviewed command on a clean worktree, never a side effect of evaluation.
- **Regression evaluation:** `python tools/evaluate.py` runs all 38 cases through both language CLIs offline, compares against goldens, validates attribution completeness, and emits a fail-closed `evaluation-report.json`. It is independent of the per-milestone gates.
- **Failure matrix and chaos exercises:** `fixtures/failure-matrix.yaml` maps every declared failure class (stable `M0-F1`…`M5-Fn` identifiers) to its expected response and the proof identity that asserts it; `tools/chaos.py` replays each fault live through the lessons' existing scripted controls and must match the matrix. Coverage tests fail on missing rows or absent proofs.

Use the existing 38 canonical cases as the evaluation set; add no new CLI cases. The M6 authority is `python scripts/verify_m6.py`: clean starting revision → invoke `verify_m5.py` once (the M5→M0 chain) → contract audit, evaluator over all cases, chaos exercises, verifier-safety suite (normal and `python -O`) → publish `.boundrelay/m6/verification-evidence.json` on an unchanged HEAD.

## Consequences

- M6 remains offline, framework-free, and TypeScript/Python-first; the evaluator and matrix are plain repo tooling.
- Result schemas across lessons gain the required attribution block — the only shared-contract change.
- Wall-clock time never enters evidence; latency is clock-injected and parity-safe.
- Goldens make regressions reviewable as diffs; the matrix makes failure responses provable on demand.
- The future M6 authority invokes M5, retaining the M5→M0 chain and current-revision evidence checks.
- Real metrics backends, OpenTelemetry, dashboards, trace inspectors, real cost APIs, random/destructive chaos, new scenarios, Go, MCP, framework mappings, and shared-runtime extraction remain outside M6.

## Design

[M6 Observability, Evaluation, and Fault Injection Design](../superpowers/specs/2026-11-03-m6-observability-evaluation-design.md)

## Acceptance gate

The owner approved the written design and this decision on 2026-11-03. Detailed implementation planning is the next artifact; reviewed-plan approval and execution-method selection are required before product implementation. No lower-milestone boundary is changed by this decision.
