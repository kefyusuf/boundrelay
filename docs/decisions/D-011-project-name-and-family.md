# D-011 — Project Name and Family

- **Status:** Accepted
- **Date:** 2026-09-02

## Decision

The project’s umbrella name is **BoundRelay** and the initial repository slug is `boundrelay`.

The name combines two architectural ideas:

- **Bound:** explicit contracts, budgets, permissions, stop conditions, state transitions, and failure boundaries;
- **Relay:** routing, delegation, handoffs, fan-out/fan-in, and coordination across implementations.

The initial repository remains one lesson-centered open-source project. **BoundRelay Learn**, **BoundRelay Protocol**, **BoundRelay Runtime**, **BoundRelay CLI**, and **BoundRelay Inspector** are reserved product-family labels. They are not separate M0 projects and must not be created until an independent artifact has a justified API and release lifecycle.

## Rationale

The previous descriptive name, `agent-orchestration-by-example`, accurately described the educational format but constrained the project to a tutorial repository. BoundRelay can represent the current curriculum while leaving room for contracts, tooling, runtime primitives, and inspection capabilities that may emerge from validated lessons.

The core brand deliberately excludes `AI`, `Agent`, and `Orchestration`. Those terms may appear in subtitles and discovery metadata without tying the long-term project identity to one implementation trend.

## Consequences

- Documentation, package metadata, repository examples, and future CLI naming use **BoundRelay** consistently.
- The canonical GitHub repository target is `<owner>/boundrelay`.
- The initial subtitle is: **“Bounded, observable agent orchestration from first principles.”**
- Package names and domains remain subject to registry and legal availability checks before publication.
- A future subproject split requires a separate accepted decision.
