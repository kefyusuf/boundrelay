# M2 Routing and Typed Handoff Design

- **Date:** 2026-09-29
- **Status:** Proposed
- **Milestone:** M2 — Routing and handoff
- **Project:** BoundRelay (boundrelay)
- **Depends on:** Foundation design, D-001 through D-012, completed M0 and M1 exact-revision verification

## 1. Purpose

M2 introduces the first explicit responsibility-transfer boundary in BoundRelay.

M0 already proved that deterministic and model-backed routing can produce the same validated route decision. M2 must not repeat that lesson. Routing remains the baseline input to a new concept: a typed handoff from a router to a deterministic specialist receiver.

The M2 teaching objective is:

> A route decision names a destination category; it does not itself authorize or complete a responsibility transfer. Handoff construction, minimum receiver context, confidence policy, receiver availability, acceptance, rejection, tracing, and verification remain deterministic orchestration responsibilities.

M2 stays framework-free, offline, and TypeScript/Python-first.

## 2. Product reassessment conclusion

The roadmap item remains valid, but its emphasis is narrowed.

M2 will still compare a code router with a scripted-model router, but only to show that both feed the same handoff boundary. M0's routing architecture is not reimplemented as a new product concept.

The new material is:

- explicit confidence policy;
- proposed route versus policy-selected route;
- typed handoff envelope;
- sender intent separated from receiver input;
- minimum-context transfer;
- deterministic receiver directory;
- handoff acceptance and rejection;
- context-loss failure;
- unavailable-receiver failure;
- cross-language parity and exact-revision evidence.

M2 does not introduce model-backed receivers or a general-purpose multi-agent runtime.

## 3. Teaching scenario

The canonical scenario is **support handoff**.

It reuses the support domain and route taxonomy already established by M0:

~~~text
billing
technical
general
~~~

The existing M0 route-decision contract remains canonical:

contracts/routing/route-decision.schema.json

The receiver mapping is fixed:

~~~text
billing   -> billing-specialist
technical -> technical-specialist
general   -> general-specialist
~~~

A support request contains exactly the receiver-facing business context needed by M2:

~~~json
{
  "ticket_id": "TCK-1001",
  "request_text": "I was charged twice for invoice INV-1001."
}
~~~

The route decision remains separate from the handoff envelope.

## 4. Scope

### Included

- lesson lessons/02-routing-handoff/;
- TypeScript and Python implementations;
- code-router mode;
- deterministic scripted-model router mode;
- reuse of the existing M0 route-decision JSON Schema;
- one explicit confidence threshold;
- deterministic fallback policy;
- typed support-handoff envelope;
- explicit sender and receiver identities;
- sender intent separated from receiver input;
- minimum receiver context;
- deterministic specialist receiver directory;
- exactly three deterministic specialist receivers;
- context-loss rejection;
- unavailable-receiver rejection;
- handoff requested/accepted/rejected events;
- M2-specific result contract;
- five canonical milestone parity cases;
- normalized TypeScript/Python parity;
- offline execution;
- exact-revision M2 verification evidence.

### Explicitly excluded

- real model providers;
- model-backed specialist receivers;
- receiver tool loops;
- parallel fan-out or fan-in;
- multiple handoffs in one run;
- handoff retry or backoff;
- receiver retry;
- persistence or checkpoints;
- resume or replay;
- side-effecting receivers;
- idempotency;
- approval workflows;
- cancellation semantics beyond existing process/test boundaries;
- Go implementation;
- MCP;
- framework adapters;
- dynamic agent discovery;
- generic agent registry;
- reusable shared runtime extraction;
- UI or trace viewer changes.

M2 must not pre-implement M3 parallelism, M4 recovery, or M5 side-effect semantics.

## 5. Router modes

M2 has two router modes:

~~~text
code
model
~~~

### Code router

The code router is deterministic and returns a schema-valid M0 route decision with confidence 1.0.

It exists as the non-model baseline and must emit no model events.

### Model router

The model router uses an offline scripted decision provider and returns an untrusted M0-shaped route decision.

The runtime validates the complete decision against the existing M0 route-decision schema before confidence policy or handoff construction.

A malformed or unknown route decision fails closed as INVALID_ROUTE_DECISION.

That boundary is covered by contract/unit tests and is not a sixth canonical parity case.

## 6. Confidence and fallback policy

The confidence threshold is fixed at 0.80.

Policy semantics:

~~~text
confidence >= 0.80
    -> selected_route = proposed_route
    -> policy_outcome = selected
    -> fallback_applied = false

confidence < 0.80
    -> selected_route = general
    -> policy_outcome = fallback
    -> fallback_applied = true
~~~

Equality is valid:

~~~text
0.80 -> selected
0.79 -> fallback
~~~

The model cannot select, bypass, or modify the fallback policy. It proposes only route + confidence.

The canonical low-confidence case proposes billing below the threshold and is therefore transferred to general-specialist.

## 7. Typed handoff envelope

M2 adds a scenario-specific handoff contract rather than prematurely defining a universal agent protocol:

contracts/handoffs/support-handoff.schema.json

Canonical shape:

~~~json
{
  "schema_version": "1.0",
  "handoff_id": "handoff-...",
  "sender": "support-router",
  "receiver": "billing-specialist",
  "sender_intent": {
    "route": "billing",
    "confidence": 1.0,
    "policy_outcome": "selected"
  },
  "receiver_input": {
    "ticket_id": "TCK-1001",
    "request_text": "I was charged twice for invoice INV-1001."
  }
}
~~~

The contract requires:

- schema_version: "1.0";
- non-empty handoff_id;
- sender: "support-router";
- receiver in exactly billing-specialist, technical-specialist, general-specialist;
- sender_intent.route in the M0 route taxonomy;
- sender_intent.confidence in [0, 1];
- sender_intent.policy_outcome in selected|fallback;
- receiver_input.ticket_id matching ^TCK-[0-9]{4}$;
- non-empty receiver_input.request_text;
- no additional properties at any envelope object boundary.

The envelope deliberately keeps sender_intent and receiver_input as separate typed objects.

The receiver does not receive router internals, model prompts, hidden reasoning, full traces, or unrelated orchestration state.

## 8. Deterministic receiver boundary

M2 registers exactly three deterministic receivers:

~~~text
billing-specialist
technical-specialist
general-specialist
~~~

Each receiver consumes only the validated receiver_input.

Conceptually:

~~~text
BillingSpecialist.handle(receiver_input)
TechnicalSpecialist.handle(receiver_input)
GeneralSpecialist.handle(receiver_input)
~~~

Receivers are not agents and do not invoke models.

A successful accepted handoff causes exactly one specialist invocation. M2 performs no receiver retry.

Unexpected implementation exceptions after an accepted boundary are test/tooling failures, not a new canonical M2 domain-failure taxonomy.

## 9. Handoff validation and dispatch order

For both router modes, orchestration applies this order:

1. obtain the route decision;
2. validate the complete route decision against the existing M0 schema;
3. if invalid, emit route.rejected and fail with INVALID_ROUTE_DECISION;
4. apply the fixed confidence policy;
5. derive selected_route, fallback_applied, and receiver name;
6. emit route.selected with proposed route, selected route, confidence, mode, and fallback outcome;
7. construct the candidate handoff envelope;
8. emit handoff.requested with the observable candidate transfer;
9. validate the complete handoff envelope;
10. if invalid, emit handoff.rejected with HANDOFF_CONTEXT_INVALID and do not invoke a receiver;
11. resolve the receiver in the deterministic receiver directory;
12. if unavailable, emit handoff.rejected with HANDOFF_RECEIVER_UNAVAILABLE and do not invoke a receiver;
13. emit handoff.accepted;
14. invoke the selected deterministic receiver exactly once;
15. terminate successfully.

No failure path may silently select another receiver except the explicit low-confidence policy fallback in step 4.

## 10. Canonical cases

M2 defines exactly five milestone-level parity cases.

| Case ID | Router mode | Purpose | Expected result |
|---|---|---|---|
| code-billing-handoff | code | Deterministic route feeds typed handoff | SUCCEEDED |
| model-technical-handoff | model | Scripted model route feeds same typed handoff | SUCCEEDED |
| model-low-confidence-fallback | model | Confidence policy forces general fallback | SUCCEEDED |
| handoff-context-loss | model | Required receiver context is omitted | FAILED / HANDOFF_CONTEXT_INVALID |
| handoff-receiver-unavailable | code | Valid handoff targets unavailable receiver | FAILED / HANDOFF_RECEIVER_UNAVAILABLE |

No sixth milestone parity case is added for invalid route decisions. That pre-handoff validation boundary is already a foundational behavior and remains covered by unit/contract tests.

### Canonical case details

#### code-billing-handoff

~~~text
ticket_id: TCK-1001
request: I was charged twice for invoice INV-1001.
proposed_route: billing
confidence: 1.0
selected_route: billing
receiver: billing-specialist
fallback_applied: false
specialist_invoked: true
~~~

#### model-technical-handoff

~~~text
ticket_id: TCK-1002
request: The verification screen keeps rejecting the code and I cannot get in.
scripted decision: technical / 0.92
selected_route: technical
receiver: technical-specialist
fallback_applied: false
specialist_invoked: true
~~~

#### model-low-confidence-fallback

~~~text
ticket_id: TCK-1003
request: Something about my invoice looks wrong but I am not sure what happened.
scripted decision: billing / 0.54
selected_route: general
receiver: general-specialist
fallback_applied: true
specialist_invoked: true
~~~

#### handoff-context-loss

~~~text
ticket_id: TCK-9001
scripted decision: billing / 0.93
failure injection: omit receiver_input.request_text
selected receiver: billing-specialist
specialist_invoked: false
failure: HANDOFF_CONTEXT_INVALID
~~~

#### handoff-receiver-unavailable

~~~text
ticket_id: TCK-9002
code route: billing / 1.0
failure injection: billing-specialist unavailable
selected receiver: billing-specialist
specialist_invoked: false
failure: HANDOFF_RECEIVER_UNAVAILABLE
~~~

## 11. Failure semantics

M2 result failures are limited to:

~~~text
INVALID_ROUTE_DECISION
HANDOFF_CONTEXT_INVALID
HANDOFF_RECEIVER_UNAVAILABLE
~~~

Only the latter two are canonical milestone parity failures.

### Invalid route decision

- fails before handoff.requested;
- emits route.rejected;
- no receiver is selected or invoked.

### Context loss

- route selection succeeds;
- handoff.requested is observable;
- envelope validation fails;
- one handoff.rejected is emitted with HANDOFF_CONTEXT_INVALID;
- no handoff.accepted;
- no specialist invocation.

### Receiver unavailable

- route selection succeeds;
- handoff envelope is schema-valid;
- handoff.requested is observable;
- receiver resolution fails;
- one handoff.rejected is emitted with HANDOFF_RECEIVER_UNAVAILABLE;
- no handoff.accepted;
- no specialist invocation.

M2 performs no handoff retry and no fallback after either handoff rejection.

## 12. Result contract

M2 uses a dedicated result contract:

contracts/results/handoff-result.schema.json

A result contains at least:

~~~json
{
  "schema_version": "1.0",
  "run_id": "run-...",
  "scenario_id": "support-handoff",
  "case_id": "model-low-confidence-fallback",
  "router_mode": "model",
  "status": "SUCCEEDED",
  "proposed_route": "billing",
  "selected_route": "general",
  "receiver": "general-specialist",
  "fallback_applied": true,
  "specialist_invoked": true,
  "failure_code": null,
  "trace_path": ".boundrelay/m2/...jsonl"
}
~~~

Success requires non-null proposed route, selected route, and receiver; specialist_invoked: true; and failure_code: null.

Canonical handoff failures retain the validated route/policy/receiver selection but require specialist_invoked: false and the corresponding handoff failure code.

INVALID_ROUTE_DECISION may use null proposed/selected/receiver fields because handoff selection never becomes valid.

## 13. Event model

The common event envelope remains schema_version: "1.0".

M2 extends the allowed event-type enum with exactly the handoff family already reserved by the foundation design:

~~~text
handoff.requested
handoff.accepted
handoff.rejected
~~~

M0 and M1 traces must remain schema-valid.

Canonical route.selected payload preserves router_mode, proposed_route, selected_route, confidence, and fallback_applied.

handoff.requested contains the candidate handoff identifiers plus observable sender_intent and receiver_input.

handoff.accepted contains at least handoff_id and receiver.

handoff.rejected contains at least handoff_id, receiver, and failure_code.

Trace data must not expose private chain-of-thought.

## 14. Deterministic fixtures

Canonical assets remain language-neutral.

M2 adds:

- fixtures/scenarios/support-handoff.yaml — requests, router modes, threshold expectations, receiver mapping, and expected results;
- fixtures/fake-model/support-handoff.yaml — deterministic model route decisions;
- fixtures/failures/support-handoff.yaml — context-loss and unavailable-receiver failure injection;
- lessons/02-routing-handoff/invariants.yaml — milestone invariants.

The failure fixture may alter only the named failure boundary for its case. It must not become a generic chaos framework.

## 15. Cross-language parity

TypeScript and Python may differ internally but must converge on observable M2 behavior.

Parity preserves:

- case ID;
- router mode;
- terminal status;
- failure code;
- proposed route;
- selected route;
- confidence policy outcome;
- fallback flag;
- receiver identity;
- handoff sender/receiver;
- sender-intent fields;
- receiver-input fields;
- handoff requested/accepted/rejected ordering;
- specialist invocation boolean/count;
- normalized event order;
- exactly one terminal run event.

Parity ignores timestamps, generated run/event/handoff identifiers, trace paths, language source identifier, stack traces, and implementation-specific class names.

## 16. Verification authority

M2 receives a dedicated authority command:

python scripts/verify_m2.py

The M2 authority must eventually:

1. require a clean worktree;
2. capture the candidate Git revision;
3. run python scripts/verify_m1.py as the lower-milestone regression authority;
4. run M2 shared contract tests;
5. run M2 TypeScript typecheck/tests;
6. run M2 Python tests;
7. execute all five canonical cases in both languages;
8. validate route-decision, handoff, result, and event schemas;
9. verify confidence-threshold equality and fallback semantics;
10. verify context-loss and unavailable-receiver no-dispatch invariants;
11. normalize and compare TypeScript/Python results and traces;
12. re-check clean worktree and the unchanged Git revision;
13. write .boundrelay/m2/verification-evidence.json bound to that exact revision.

M1 remains independently runnable; because M1 authority already runs M0, M2 does not need a second direct M0 invocation.

GitHub Actions must execute the same M2 authority command.

## 17. Required invariants

The implementation plan must encode at least these invariants:

1. Code-router mode never invokes the model.
2. Every model route decision is validated before confidence policy or handoff construction.
3. The existing M0 route-decision schema remains the route-decision authority.
4. confidence >= 0.80 preserves the proposed route.
5. confidence < 0.80 forces general with fallback_applied: true.
6. The model cannot bypass or redefine confidence policy.
7. Route-to-receiver mapping is exactly billing/technical/general to their three named specialists.
8. Handoff sender intent and receiver input remain separate typed objects.
9. Receiver input contains only minimum support context: ticket_id and request_text.
10. Invalid handoff context emits one requested + one rejected handoff and invokes no specialist.
11. Unavailable receiver emits one requested + one rejected handoff and invokes no specialist.
12. Successful handoff emits requested + accepted and invokes exactly one deterministic specialist.
13. No handoff failure retries automatically.
14. Every run emits exactly one terminal event with monotonic event sequence numbers.
15. TypeScript and Python produce equivalent normalized M2 behavior.
16. M2 evidence is bound to the exact candidate revision.
17. M1 authority remains green.

## 18. Planned repository shape

~~~text
contracts/
├── handoffs/
│   └── support-handoff.schema.json
├── results/
│   └── handoff-result.schema.json
├── routing/
│   └── route-decision.schema.json          # reuse unchanged
└── events/
    └── run-event.schema.json               # extend enum only; envelope remains v1.0

fixtures/
├── scenarios/
│   └── support-handoff.yaml
├── fake-model/
│   └── support-handoff.yaml
└── failures/
    └── support-handoff.yaml

lessons/
└── 02-routing-handoff/
    ├── README.md
    ├── invariants.yaml
    ├── typescript/
    └── python/

tools/
└── parity/
    └── verify_m2.py

scripts/
└── verify_m2.py

.github/workflows/
└── m2.yml
~~~

M2 remains lesson-local. It must not extract a shared router, handoff runtime, receiver framework, or generic agent directory from earlier lessons.

## 19. Acceptance criteria

M2 is complete only when all of the following are true for the exact candidate revision:

- code-router billing handoff succeeds without model events;
- model-router technical handoff succeeds;
- low-confidence model decision is routed to general-specialist by deterministic policy;
- threshold equality 0.80 is covered and remains selected rather than fallback;
- context-loss case emits handoff requested/rejected and causes zero specialist invocations;
- unavailable-receiver case emits handoff requested/rejected and causes zero specialist invocations;
- successful handoffs invoke exactly one deterministic receiver;
- sender intent and receiver input are separately observable and schema-valid;
- no receiver receives more than ticket_id + request_text;
- all M2 results and events validate against shared contracts;
- M0 and M1 behavior remains valid through the M1 authority;
- normalized TypeScript/Python behavior matches for all five canonical cases;
- local and CI verification use the same M2 authority command;
- M2 evidence records the exact Git revision.

## 20. Governance and implementation-planning gate

This design is **Proposed**.

The human project owner approved the conversational M2 direction on 2026-09-29, which authorizes writing this design proposal but does not authorize implementation.

- D-013 remains Proposed until this written design is reviewed and explicitly accepted.
- No M2 implementation plan may be written until the written spec is approved.
- No M2 product code, contract implementation, fixture implementation, or workflow implementation is part of this design change.
- Any material change to canonical cases, confidence threshold, route taxonomy, receiver topology, handoff envelope, failure taxonomy, side-effect policy, or verification authority must return to the decision gate.
