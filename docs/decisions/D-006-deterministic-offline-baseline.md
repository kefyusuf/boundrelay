# D-006 — Deterministic Offline Baseline

- **Status:** Accepted
- **Date:** 2026-09-02

## Decision

Every lesson must run without network access or an API key using a scripted fake model or decision provider capable of both success and failure trajectories.

## Consequences

Deterministic CI, repeatable exercises, stable fault injection, and low-cost onboarding are mandatory. Real providers are optional extensions.
