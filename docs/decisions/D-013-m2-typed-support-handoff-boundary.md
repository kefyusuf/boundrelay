# D-013 — M2 Typed Support Handoff Boundary

- **Status:** Accepted
- **Date:** 2026-09-30

## Decision

M2 proposes to teach routing-to-handoff responsibility transfer through one offline support-handoff lesson in TypeScript and Python.

M2 will reuse the existing M0 route-decision contract and route taxonomy. Code routing versus scripted-model routing remains a baseline comparison only; M2's new architectural subject is a typed handoff envelope between support-router and one deterministic specialist receiver.

The fixed route-to-receiver mapping is:

~~~text
billing   -> billing-specialist
technical -> technical-specialist
general   -> general-specialist
~~~

A deterministic confidence policy owns fallback:

~~~text
confidence >= 0.80 -> selected route
confidence < 0.80  -> general fallback
~~~

The model cannot choose or bypass that policy.

The handoff contract keeps sender_intent separate from minimum receiver_input. Receivers obtain only ticket_id and request_text; they do not receive router internals, prompts, hidden reasoning, or full orchestration state.

M2 receivers remain deterministic functions, not model-backed agents.

The canonical M2 milestone contains exactly five parity cases:

- code billing handoff success;
- model technical handoff success;
- model low-confidence fallback success;
- handoff context-loss failure;
- handoff receiver-unavailable failure.

M2 handoff failures are limited to HANDOFF_CONTEXT_INVALID and HANDOFF_RECEIVER_UNAVAILABLE. Invalid route decisions remain a pre-handoff fail-closed boundary and are not a sixth milestone parity case.

## Consequences

- The common event envelope remains version 1.0 and adds only handoff.requested, handoff.accepted, and handoff.rejected.
- M2 gets a scenario-specific support-handoff schema rather than a premature universal agent protocol.
- M2 gets a dedicated handoff result contract.
- Low-confidence fallback is deterministic orchestration policy, not model behavior.
- Rejected handoffs never invoke a specialist.
- Successful handoffs invoke exactly one deterministic specialist.
- Handoff retry, persistence, side effects, approval, model-backed receivers, multi-agent topology, parallelism, Go, MCP, real providers, framework adapters, and shared-runtime extraction remain outside M2.
- M2 completion requires TypeScript/Python behavioral parity and exact-revision evidence.
- M2 verification must retain M1 as the lower-milestone regression authority.

## Design

docs/superpowers/specs/2026-09-29-m2-routing-handoff-design.md

## Acceptance

Accepted by the human project owner on 2026-09-30 after review of the linked written design.

Detailed M2 implementation planning may proceed from the accepted design. Any material change to the accepted M2 boundaries requires a new governance decision or an explicit superseding decision.
