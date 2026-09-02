# Foundation Design: BoundRelay

- **Date:** 2026-09-02
- **Status:** Accepted for M0 implementation planning
- **Project:** **BoundRelay** (`boundrelay`)
- **Design class:** New educational repository and executable learning system

## 1. Purpose

**BoundRelay** will teach bounded, observable agent orchestration from first principles by implementing the same progressively harder scenarios in TypeScript, Python, and later Go.

The repository is designed for three overlapping audiences:

1. Developers who can write software but are new to agent architecture.
2. Automation builders who understand workflows but not production agent runtimes.
3. People using coding agents to create systems without enough language depth to evaluate the generated architecture.

The project will not promise that users can safely deploy production agents without understanding software engineering. Instead, it will make the important decisions, boundaries, failure modes, and evidence visible enough that a learner can reason about generated code and ask the right questions.

## 2. Project identity

**BoundRelay** is the stable umbrella brand and `boundrelay` is the initial repository slug. The name encodes the project’s two primary concerns:

- **Bound:** agentic judgment and execution are constrained by explicit contracts, schemas, budgets, permissions, stop conditions, state transitions, and failure policies.
- **Relay:** work moves through routing, delegation, handoffs, parallel workers, synthesizers, and language implementations without losing observable responsibility.

The initial repository remains a single lesson-centered system. The following names define a possible future project family, but they are not separate deliverables in M0:

- **BoundRelay Learn:** curriculum and executable lessons;
- **BoundRelay Protocol:** language-neutral schemas, events, handoffs, and invariants;
- **BoundRelay Runtime:** reusable bounded-execution primitives;
- **BoundRelay CLI:** lesson, run, trace, and parity commands;
- **BoundRelay Inspector:** trace and execution visualization.

A subproject may be split out only after it has an independent API, release lifecycle, ownership boundary, and user need. This prevents the brand decision from causing premature framework or monorepo expansion.

## 3. Problem statement

Current learning material frequently starts with a framework and optimizes for a successful demonstration. This creates several recurring failures:

- workflows, agents, subagents, routers, and orchestrators are treated as synonyms;
- deterministic business rules are delegated to an LLM unnecessarily;
- agent roles are created before task boundaries are justified;
- state is confused with chat history or memory;
- retries duplicate side effects;
- agent handoffs use unvalidated prose;
- multi-agent systems add latency and context loss without real parallelism;
- success is inferred from a plausible response rather than verification evidence;
- examples omit cancellation, partial failure, budgets, auditability, and recovery.

The repository will correct this by teaching architecture selection before framework syntax.

## 4. Product principles

### 4.1 Start with the non-agent baseline

Every scenario begins with the simplest deterministic implementation. Agentic behavior is added only after a specific limitation is demonstrated.

### 4.2 Scenarios and contracts are canonical

No language implementation is the source of truth. Canonical artifacts are language-neutral and machine-verifiable.

### 4.3 Observable behavior, not source-code similarity

Implementations may differ internally. Parity is measured through schemas, normalized events, state transitions, and behavioral invariants.

### 4.4 Failure is part of the lesson

Each lesson includes an intentionally naive version, at least one controlled failure, the corrected design, and a regression test that proves the failure remains addressed.

### 4.5 Offline-first learning path

Every lesson must have a deterministic fake model or decision provider. API keys and network access are optional extensions, never prerequisites for learning or CI.

### 4.6 Deterministic orchestration, bounded model judgment

Known sequencing, permissions, retry policy, budgets, and irreversible actions remain code-controlled. LLM judgment is used only where interpretation, decomposition, or synthesis genuinely requires it.

### 4.7 Single-agent baseline before multi-agent topology

A multi-agent version must demonstrate a measurable need such as independent parallel work, context isolation, model specialization, adversarial validation, or long-running independent responsibilities.

### 4.8 External evidence over agent self-report

An agent saying “done” is not completion evidence. Completion is decided from current-revision tests, schema validation, state transition checks, trace assertions, and scenario-specific verification.

### 4.9 No private reasoning dependency

The project records inputs, outputs, tool calls, decisions expressed as structured outcomes, state transitions, and verification evidence. It does not require or expose private chain-of-thought.

### 4.10 Progressive disclosure

A learner sees only the concepts required for the current lesson. Production concerns are introduced early enough to shape habits, but infrastructure is not added before the lesson needs it.

## 5. Scope boundaries

### Included

- deterministic workflows with bounded LLM steps;
- single-agent loops;
- routing and handoffs;
- orchestrator–worker and evaluator patterns;
- parallel fan-out/fan-in;
- typed state and event contracts;
- budgets, cancellation, retries, and timeouts;
- checkpoints, resume, and replay;
- idempotency and side-effect controls;
- human approval;
- tracing and evaluation;
- cross-language behavioral parity;
- optional provider and framework mappings.

### Excluded from the initial project

- a hosted SaaS platform;
- a drag-and-drop workflow editor;
- a general-purpose agent framework;
- a model gateway;
- a vector database or generic memory product;
- autonomous self-modification;
- a marketplace for agents or skills;
- production deployment templates for every cloud;
- language-by-language courses unrelated to orchestration.

## 6. Repository architecture

The repository is lesson-centered rather than language-centered.

```text
boundrelay/
├── README.md
├── README.tr.md
├── ROADMAP.md
├── contracts/
│   ├── events/
│   ├── state/
│   ├── handoffs/
│   └── results/
├── fixtures/
│   ├── scenarios/
│   ├── fake-model/
│   ├── failures/
│   └── golden-traces/
├── lessons/
│   ├── 00-workflow-or-agent/
│   │   ├── README.md
│   │   ├── scenario.yaml
│   │   ├── invariants.yaml
│   │   ├── typescript/
│   │   ├── python/
│   │   └── go/
│   └── ...
├── tools/
│   ├── parity/
│   ├── trace-normalizer/
│   └── fault-injection/
├── framework-mappings/
├── trace-viewer/
├── docs/
│   ├── design/
│   ├── decisions/
│   ├── glossary/
│   └── production/
└── .ai/
    ├── knowledge/
    ├── governance/
    ├── delivery/
    └── runtime/
```

The `go/` directory may be absent from early lessons until M7. Its absence is explicit rollout status, not an empty placeholder.

## 7. Lesson contract

Each lesson is a self-contained learning unit with the following required sections and assets.

### 7.1 Human-readable sections

1. Problem.
2. Success criteria.
3. Deterministic baseline.
4. Reason to introduce model judgment.
5. Naive implementation.
6. Failure injection.
7. Corrected implementation.
8. Verification evidence.
9. Trade-offs.
10. When not to use this pattern.
11. Exercises.

### 7.2 Machine-readable assets

- `scenario.yaml`: fixed inputs, expected categories, and constraints;
- `invariants.yaml`: behavior that every language must satisfy;
- input/output JSON Schemas;
- deterministic fake-model trajectory;
- injected failure fixtures;
- normalized golden trace where exact order is deterministic;
- semantic trace assertions where concurrency makes exact order inappropriate.

## 8. Shared execution model

### 8.1 Core entities

- **Scenario:** The language-neutral problem definition.
- **Run:** One execution of a scenario against a specific implementation revision.
- **Step:** A bounded unit of workflow execution.
- **Agent:** A model-backed decision component with explicit tools, limits, input, and output.
- **Tool:** A typed capability whose side-effect class is declared.
- **Handoff:** A typed transfer of responsibility and minimum required context.
- **Checkpoint:** Persisted execution state sufficient to resume safely.
- **Evidence:** Verification output bound to the implementation revision and run.

### 8.2 Minimum run states

```text
CREATED → RUNNING → SUCCEEDED
                  ↘ FAILED
                  ↘ PAUSED
                  ↘ CANCELLED
                  ↘ UNKNOWN
```

`UNKNOWN` is required when the system cannot prove whether an external side effect occurred. It must not be flattened into either success or failure.

### 8.3 Event model

The initial common event envelope is:

```json
{
  "schema_version": "1.0",
  "event_id": "evt-...",
  "run_id": "run-...",
  "sequence": 1,
  "type": "step.started",
  "timestamp": "2026-09-02T00:00:00Z",
  "source": "typescript",
  "data": {}
}
```

Initial event families:

- `run.created`, `run.started`, `run.paused`, `run.completed`, `run.failed`, `run.cancelled`;
- `step.started`, `step.completed`, `step.failed`, `step.skipped`;
- `model.requested`, `model.completed`, `model.failed`;
- `tool.requested`, `tool.completed`, `tool.failed`, `tool.duplicate_suppressed`;
- `route.selected`, `route.rejected`;
- `handoff.requested`, `handoff.accepted`, `handoff.rejected`;
- `checkpoint.saved`, `checkpoint.restored`;
- `approval.requested`, `approval.granted`, `approval.rejected`;
- `budget.consumed`, `budget.exceeded`;
- `verification.started`, `verification.passed`, `verification.failed`.

The event schema stores observable system behavior. It does not contain hidden model reasoning.

## 9. Cross-language parity

Parity does not require identical source code, log formatting, stack traces, timestamps, or asynchronous scheduling order.

Parity requires:

- the same scenario inputs;
- schema-valid inputs, outputs, handoffs, and events;
- the same externally visible state transitions;
- the same handling of declared failure classes;
- the same side-effect safety guarantees;
- the same pass/fail result for each behavioral invariant;
- compatible normalized trace semantics.

### 9.1 Trace normalization

The normalizer removes or canonicalizes fields that are expected to differ:

- timestamps;
- generated identifiers;
- language/runtime metadata;
- stack traces;
- timing values;
- ordering of events declared commutative by the scenario.

It preserves fields that prove behavior:

- event type;
- step name;
- route;
- tool identity;
- handoff sender and receiver;
- status transition;
- failure code;
- idempotency outcome;
- approval outcome;
- verification result.

## 10. Deterministic fake model

The fake model is a scripted decision provider, not a mock that always succeeds. A fixture defines a trajectory such as:

```yaml
responses:
  - when:
      call: classify_request
      input_contains: "charged twice"
    return:
      route: billing
      confidence: 0.98
  - when:
      call: classify_request
      input_contains: "invalid-route-case"
    return:
      route: unknown-specialist
      confidence: 0.99
```

The fake provider must support:

- valid structured responses;
- malformed responses;
- unknown routes or tools;
- transient provider failures;
- permanent provider failures;
- delayed responses and timeout simulation;
- repeated decisions for loop testing;
- token and cost metadata for budget exercises.

Real providers plug into the same boundary but are excluded from deterministic parity CI.

## 11. M0 design

### 11.1 Scenario

A support request is classified into one of three routes:

- `billing`;
- `technical`;
- `general`.

The deterministic baseline uses explicit keywords and rules. The bounded model version returns a structured route and confidence. An unknown route is rejected and converted into a safe fallback outcome.

### 11.2 M0 learning objectives

The learner will understand:

- why a fixed rule may be superior to an LLM router;
- the difference between decision output and orchestration control;
- why structured outputs require runtime validation;
- how the same behavior can be implemented idiomatically in two languages;
- why trace parity is more useful than source-code parity;
- how a plausible but invalid model response must fail closed.

### 11.3 M0 implementation boundaries

TypeScript and Python implementations each expose the same conceptual interfaces:

```text
DecisionProvider.classify(request) -> RouteDecision
Router.route(decision) -> RouteResult
EventSink.emit(event) -> void
ScenarioRunner.run(scenario) -> RunResult
```

Names may follow language conventions. The contracts and behavior remain shared.

### 11.4 M0 verification invariants

1. A billing fixture resolves to `billing`.
2. A technical fixture resolves to `technical`.
3. A general fixture resolves to `general`.
4. An unknown route never invokes a specialist.
5. An unknown route produces `route.rejected` and a non-success run result.
6. Every run emits one terminal run event.
7. Event sequence numbers are monotonic within a run.
8. All events validate against the shared event schema.
9. TypeScript and Python produce equivalent normalized traces for deterministic fixtures.
10. No network request is made in offline mode.

## 12. Testing and evidence

### 12.1 Test layers

- **Contract tests:** shared schemas and fixture validity.
- **Unit tests:** language-specific implementation units.
- **Scenario tests:** one implementation against canonical fixtures.
- **Parity tests:** normalized behavioral comparison across languages.
- **Failure tests:** each declared failure produces the expected safe state.
- **Documentation smoke tests:** documented commands execute successfully.

### 12.2 Evidence rules

Evidence is valid only when it records:

- repository revision;
- implementation and runtime version;
- scenario identifier;
- verification command;
- result status;
- relevant trace or report location.

A passing result from an earlier revision becomes stale when affected files or contracts change.

## 13. Error and safety model

Errors are typed into at least these categories:

- validation;
- model provider;
- tool execution;
- orchestration policy;
- budget;
- timeout/cancellation;
- side-effect ambiguity;
- verification.

Safety principles:

- validation fails closed;
- retries are bounded;
- cancellation propagates;
- side effects declare risk and idempotency policy;
- irreversible actions require approval where configured;
- partial failure remains partial failure;
- unknown external outcome becomes `UNKNOWN`;
- no secret is written into traces or fixtures;
- tools receive minimum necessary permissions.

## 14. Framework policy

The core curriculum begins with raw language and provider boundaries. Framework mappings are secondary implementations of already-understood patterns.

Every framework mapping must answer:

1. Which core primitives does the framework provide?
2. Which application responsibilities remain?
3. What context and control flow become less visible?
4. How are state, retries, recovery, and tracing implemented?
5. How can the lesson be migrated away from the framework?

Framework mappings must not become the canonical lesson implementation.

## 15. Documentation and localization

- English is the canonical documentation language for repository reach and external contribution.
- Turkish overviews and selected lesson translations are maintained alongside canonical content.
- Machine-readable scenarios and schemas are language-neutral.
- Code comments explain non-obvious orchestration decisions, not language syntax already apparent from the code.
- Documentation changes and implementation changes are reviewed together.

## 16. Project-development context

Project-development instructions, current delivery state, AI-assisted workflow records, and ephemeral session artifacts live under `.ai/`. Educational lesson content remains in the normal source tree because it is the product itself.

Knowledge is separated into:

- accepted project truth;
- governance and schemas;
- current delivery state;
- execution history and evidence;
- learned guidance pending promotion;
- ephemeral session context.

No single ever-growing context file is used as a general memory store.

## 17. Success metrics

The first release is successful when:

- a learner can explain workflow versus agent versus orchestrator after lesson 00;
- every lesson runs offline before any provider configuration;
- a failure can be reproduced deterministically;
- a correction is protected by an executable regression test;
- TypeScript and Python implementations pass the same invariants;
- adding a language does not require copying conceptual documentation;
- framework adapters can change without changing canonical contracts;
- examples remain small enough to understand without hiding production-relevant behavior.

## 18. Risks and mitigations

| Risk | Mitigation |
|---|---|
| The repository becomes three separate courses | Lesson-centered structure and shared contracts. |
| Exact trace comparison becomes brittle | Normalize unstable fields and assert semantic invariants. |
| The fake model becomes unrealistically easy | Script malformed outputs, delays, failures, loops, and budget metadata. |
| Production topics overwhelm beginners | Progressive disclosure and one new mechanism per lesson. |
| Framework churn invalidates the course | Framework-free canonical lessons; adapters are replaceable. |
| Scope expands into a platform | Explicit non-goals and milestone gates. |
| Agent examples normalize unsafe automation | Fail-closed validation, bounded execution, permissions, approval, and evidence from the first relevant lesson. |
| Go implementation drifts | Add Go only after stable contracts; enforce parity CI. |

## 19. First implementation boundary

The first implementation plan must cover only M0. It must not include:

- real LLM providers;
- Go;
- checkpoint databases;
- web UI;
- framework adapters;
- MCP;
- distributed queues;
- general-purpose plugin architecture.

M0 exists to prove the repository's contract, pedagogy, and parity model. Features that do not contribute to that proof are deferred.
