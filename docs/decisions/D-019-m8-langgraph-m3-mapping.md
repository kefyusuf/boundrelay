# D-019 — M8 LangGraph × M3 Mapping

- **Status:** Proposed
- **Date:** 2026-11-05

## Context

M7 is integrated and certified on main. D-008 allows frameworks as optional mappings once the underlying pattern is taught, requiring every mapping to document hidden control, retained responsibilities, and an exit path. The roadmap's M8 lists five candidate frameworks; mapping all of them in one milestone would be unreviewable.

The M3 lesson (bounded fan-out/fan-in) is the most instructive first collision: LangGraph's graph-of-nodes model directly parallels the orchestrator pattern, and its parallel dispatch, state channels, and built-in checkpointing collide instructively with M3's invariants (bounded admission, failure taxonomy, canonical ordering, envelope-based traces).

## Decision

Bound M8 to **one mapping: LangGraph (Python) × M3 `order-brief`**:

- The mapping lives at `mappings/langgraph-m3/python/` with its own package and an exactly-pinned LangGraph dependency — the repository's first third-party runtime dependency, isolated so that no lesson, contract, gate, evaluator, or Go module may reference it (proven by a dependency-isolation test).
- The mapping reads the canonical M3 fixtures and closed result schema; it emits LangGraph's native stream format, not the shared envelope — trace parity is explicitly out of scope and that exclusion is teaching content.
- Business-result parity is the only parity bound: all six M3 cases must produce M3-schema-valid results whose business projections equal the existing goldens, including failure-taxonomy preservation and completion-order independence.
- D-008's four questions (provided / retained / hidden / exit) are answered in the mapping README with executable proof; the centerpiece finding is that bounded admission is not a first-class LangGraph primitive and must be re-established inside the framework.
- The M8 authority `python scripts/verify_m8.py` chains `verify_m7.py` once (the M7→M0 chain), runs the mapping suite (six parity cases, isolation, four-question assertions), and publishes `.boundrelay/m8/verification-evidence.json` on an unchanged HEAD.

The other four frameworks, other lessons, LangGraph-checkpointing-as-M4-semantics, LLM/network use, and Go framework mappings (Eino) remain outside M8.

## Consequences

- The repo gains its first framework dependency, confined to `mappings/`; the canonical lessons stay framework-free.
- Framework telemetry opacity and admission-timing differences are documented findings, not defects.
- The future M8 authority invokes M7, retaining the M7→M0 chain and current-revision evidence checks.
- Real LLM calls, additional frameworks, mapping-driven goldens, and shared-runtime extraction remain outside M8.

## Design

[M8 Framework Mapping Design (LangGraph × M3)](../superpowers/specs/2026-11-05-m8-framework-mapping-design.md)

## Acceptance gate

This decision is proposed together with the written design. Owner approval of both is required before detailed implementation planning; reviewed-plan approval and execution-method selection are required before product implementation. No lower-milestone boundary is changed by this decision.
