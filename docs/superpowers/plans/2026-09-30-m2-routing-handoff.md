# M2 Routing and Typed Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the accepted M2 support-handoff lesson as an offline, deterministic, typed responsibility-transfer boundary with TypeScript/Python behavioral parity, deterministic confidence fallback, fail-closed handoff rejection, and revision-bound verification.

**Architecture:** M2 reuses the existing M0 route-decision contract and keeps routing lesson-local. A validated route decision passes through a fixed confidence policy, then into a scenario-specific typed handoff envelope whose sender intent and minimum receiver input are validated before deterministic receiver resolution and invocation. TypeScript and Python implement the same canonical five cases independently and are compared through shared contracts and normalized traces.

**Tech Stack:** Node.js 24, TypeScript 7.0.2, Vitest 4.1.7, Ajv 8.20.0, YAML 2.9.0; Python 3.14, PyYAML 6.0.3, jsonschema 4.26.0; JSON Schema draft 2020-12; GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-29-m2-routing-handoff-design.md`

## Global Constraints

- Reuse `contracts/routing/route-decision.schema.json` unchanged as the route-decision authority.
- Canonical route taxonomy remains exactly `billing|technical|general`.
- Router modes are exactly `code|model`.
- Confidence threshold is exactly `0.80`; equality selects the proposed route, values below it fall back to `general`.
- Route-to-receiver mapping is exactly billing → `billing-specialist`, technical → `technical-specialist`, general → `general-specialist`.
- Handoff sender is exactly `support-router`.
- Receiver input contains exactly `ticket_id + request_text`; no prompts, hidden reasoning, full traces, or unrelated orchestration state.
- M2 defines exactly five milestone parity cases.
- Canonical handoff failures are exactly `HANDOFF_CONTEXT_INVALID` and `HANDOFF_RECEIVER_UNAVAILABLE`; `INVALID_ROUTE_DECISION` remains a pre-handoff fail-closed boundary covered by unit/contract tests.
- Successful handoffs invoke exactly one deterministic specialist; rejected handoffs invoke zero.
- No automatic handoff or receiver retry.
- Shared event envelope remains schema version `1.0`; M2 adds only `handoff.requested`, `handoff.accepted`, and `handoff.rejected`.
- M2 remains lesson-local; do not extract a shared router, receiver framework, generic agent registry, or reusable runtime.
- No real providers, receiver agents, tool loops, parallelism, persistence, side effects, approval/idempotency, Go, MCP, framework adapters, or UI changes.
- M2 verification must invoke `python scripts/verify_m1.py` as the lower-milestone regression authority.
- Every canonical run must remain offline and produce exact-revision evidence.

## Review Focus

1. **Threshold edge:** `confidence == 0.80` must preserve the proposed route; `0.79` must fall back to `general`. Task 2 and Task 4 pin both values.
2. **Post-route fail-closed boundary:** malformed/unknown model route decisions must fail before `handoff.requested` or receiver resolution. Task 3 and Task 5 pin this.
3. **Minimum receiver context:** handoff validation must reject missing or additional receiver-input fields; receivers must observe only `ticket_id` and `request_text`. Tasks 1–5 pin this at schema, loader, and runtime boundaries.
4. **Failure-fixture isolation:** context-loss and unavailable-receiver injection must affect only their named cases; normal cases must not inherit failure behavior. Task 2 and Task 4 pin fixture isolation.
5. **Unexpected receiver exception:** after an accepted handoff, an injected receiver exception is a tooling/runtime error, not a new M2 domain failure and not a retry trigger. Task 3 and Task 5 pin this behavior.

---

## Repository File Map

### Shared contracts and fixtures

- Create `contracts/handoffs/support-handoff.schema.json` — scenario-specific typed handoff envelope.
- Create `contracts/results/handoff-result.schema.json` — M2 public run result.
- Modify `contracts/events/run-event.schema.json` — add exactly three handoff event types.
- Reuse unchanged `contracts/routing/route-decision.schema.json`.
- Create `fixtures/scenarios/support-handoff.yaml` — five canonical cases and expected observable values.
- Create `fixtures/fake-model/support-handoff.yaml` — scripted model route decisions for model-mode cases.
- Create `fixtures/failures/support-handoff.yaml` — only context-loss and unavailable-receiver injections.
- Create `lessons/02-routing-handoff/invariants.yaml` — executable M2 invariants.
- Create `tools/contracts/test_m2_contracts.py` — shared fixture/schema contract gate.

### TypeScript lesson

- Create `lessons/02-routing-handoff/typescript/package.json`
- Create `lessons/02-routing-handoff/typescript/package-lock.json`
- Create `lessons/02-routing-handoff/typescript/tsconfig.json`
- Create `lessons/02-routing-handoff/typescript/src/types.ts`
- Create `lessons/02-routing-handoff/typescript/src/paths.ts`
- Create `lessons/02-routing-handoff/typescript/src/schemas.ts`
- Create `lessons/02-routing-handoff/typescript/src/scenario.ts`
- Create `lessons/02-routing-handoff/typescript/src/scripted-router.ts`
- Create `lessons/02-routing-handoff/typescript/src/policy.ts`
- Create `lessons/02-routing-handoff/typescript/src/receivers.ts`
- Create `lessons/02-routing-handoff/typescript/src/trace.ts`
- Create `lessons/02-routing-handoff/typescript/src/runner.ts`
- Create `lessons/02-routing-handoff/typescript/src/cli.ts`
- Create focused tests under `lessons/02-routing-handoff/typescript/test/`.

### Python lesson

- Create `lessons/02-routing-handoff/python/pyproject.toml`
- Create package `lessons/02-routing-handoff/python/src/boundrelay_m2/`
- Foundation modules: `types.py`, `paths.py`, `schemas.py`, `scenario.py`, `scripted_router.py`, `policy.py`, `receivers.py`.
- Runtime modules: `trace.py`, `runner.py`, `cli.py`, `__main__.py`.
- Create focused tests under `lessons/02-routing-handoff/python/tests/`.

### Verification and documentation

- Modify `tools/parity/normalize.py` only to normalize M2-generated `handoff_id` values.
- Modify `tools/parity/test_normalize.py` for that narrow behavior.
- Create `tools/parity/verify_m2.py`.
- Create `tools/parity/test_m2_verification_safety.py`.
- Create `scripts/verify_m2.py`.
- Create `lessons/02-routing-handoff/README.md`.
- Create `.github/workflows/m2.yml`.
- Modify `README.md` and `README.tr.md` only after implementation/certification exists.

---

### Task 1: Add canonical M2 contracts, fixtures, and invariants

**Files:**
- Create: `contracts/handoffs/support-handoff.schema.json`
- Create: `contracts/results/handoff-result.schema.json`
- Modify: `contracts/events/run-event.schema.json`
- Create: `fixtures/scenarios/support-handoff.yaml`
- Create: `fixtures/fake-model/support-handoff.yaml`
- Create: `fixtures/failures/support-handoff.yaml`
- Create: `lessons/02-routing-handoff/invariants.yaml`
- Create: `tools/contracts/test_m2_contracts.py`
- Reuse unchanged: `contracts/routing/route-decision.schema.json`

**Interfaces:**
- Consumes: accepted M2 design and existing M0 route-decision contract.
- Produces:
  - canonical `support-handoff` scenario;
  - handoff/result schemas;
  - exact five-case fixture set;
  - exact two handoff failure injections;
  - M2 invariant set;
  - three new allowed event types.

- [ ] **Step 1: Write failing M2 contract tests**

Create `tools/contracts/test_m2_contracts.py` and assert:

~~~python
EXPECTED_CASES = {
    "code-billing-handoff",
    "model-technical-handoff",
    "model-low-confidence-fallback",
    "handoff-context-loss",
    "handoff-receiver-unavailable",
}
self.assertEqual({case["id"] for case in scenario["cases"]}, EXPECTED_CASES)
self.assertEqual(scenario["confidence_threshold"], 0.80)
self.assertEqual(
    scenario["route_receivers"],
    {
        "billing": "billing-specialist",
        "technical": "technical-specialist",
        "general": "general-specialist",
    },
)
~~~

Also assert the existing route-decision schema still accepts `{"route":"billing","confidence":0.80}`, rejects unknown routes, and has not gained M2-only fields.

For `support-handoff.schema.json`, pin:

- sender exactly `support-router`;
- receiver enum exactly the three accepted specialists;
- `sender_intent.route` uses the M0 route taxonomy;
- `policy_outcome` is `selected|fallback`;
- `ticket_id` matches `^TCK-[0-9]{4}$`;
- `request_text` is non-empty;
- receiver input rejects additional fields;
- every nested object rejects additional properties.

For `handoff-result.schema.json`, assert success, handoff-failure, and invalid-route shapes separately.

- [ ] **Step 2: Run the contract test and verify RED**

Run:

~~~bash
python -m unittest tools.contracts.test_m2_contracts -v
~~~

Expected: FAIL because M2 schemas/fixtures do not exist.

- [ ] **Step 3: Add the exact canonical scenario fixture**

The document begins with:

~~~yaml
schema_version: "1.0"
scenario_id: support-handoff
confidence_threshold: 0.80
route_receivers:
  billing: billing-specialist
  technical: technical-specialist
  general: general-specialist
~~~

Use this five-case observable matrix:

| Case | mode | proposed | confidence | selected | receiver | fallback | invoked | outcome |
|---|---|---:|---:|---|---|---:|---:|---|
| `code-billing-handoff` | code | billing | 1.00 | billing | billing-specialist | false | true | SUCCEEDED |
| `model-technical-handoff` | model | technical | 0.92 | technical | technical-specialist | false | true | SUCCEEDED |
| `model-low-confidence-fallback` | model | billing | 0.54 | general | general-specialist | true | true | SUCCEEDED |
| `handoff-context-loss` | model | billing | 0.93 | billing | billing-specialist | false | false | HANDOFF_CONTEXT_INVALID |
| `handoff-receiver-unavailable` | code | billing | 1.00 | billing | billing-specialist | false | false | HANDOFF_RECEIVER_UNAVAILABLE |

Pin the exact requests:

~~~text
TCK-1001: I was charged twice for invoice INV-1001.
TCK-1002: The verification screen keeps rejecting the code and I cannot get in.
TCK-1003: Something about my invoice looks wrong but I am not sure what happened.
TCK-9001: I was billed for a service I did not receive.
TCK-9002: I need help with a charge on invoice INV-9002.
~~~

Each case records `expected_policy_outcome` as `selected` except low-confidence fallback, which records `fallback`.

- [ ] **Step 4: Add deterministic model and failure fixtures**

`fixtures/fake-model/support-handoff.yaml` begins with `schema_version: "1.0"`, `scenario_id: support-handoff`, and a `decisions:` mapping containing only model-mode decisions:

~~~yaml
decisions:
  model-technical-handoff:
  return: {route: technical, confidence: 0.92}
  model-low-confidence-fallback:
    return: {route: billing, confidence: 0.54}
  handoff-context-loss:
    return: {route: billing, confidence: 0.93}
~~~

`fixtures/failures/support-handoff.yaml` begins with `schema_version: "1.0"`, `scenario_id: support-handoff`, and a `failures:` mapping containing only:

~~~yaml
failures:
  handoff-context-loss:
  omit_receiver_input_fields: [request_text]
  handoff-receiver-unavailable:
    unavailable_receivers: [billing-specialist]
~~~

Do not add generic mutation operators.

- [ ] **Step 5: Add handoff/result schemas and extend the event enum**

`support-handoff.schema.json` implements the exact envelope from the spec.

`handoff-result.schema.json` requires:

~~~text
schema_version
run_id
scenario_id
case_id
router_mode
status
proposed_route
selected_route
receiver
fallback_applied
specialist_invoked
failure_code
trace_path
~~~

Failure code is one of:

~~~text
INVALID_ROUTE_DECISION
HANDOFF_CONTEXT_INVALID
HANDOFF_RECEIVER_UNAVAILABLE
null
~~~

For successful results, route/receiver fields are non-null, `specialist_invoked=true`, and failure is null.

For the two handoff failures, proposed/selected/receiver remain non-null, `specialist_invoked=false`, and the exact handoff failure code is required.

For `INVALID_ROUTE_DECISION`, proposed/selected/receiver are null, fallback is false, and specialist invocation is false.

Extend only the event-type enum with:

~~~text
handoff.requested
handoff.accepted
handoff.rejected
~~~

Do not change the envelope version or M0/M1 event names.

- [ ] **Step 6: Add M2 invariants**

Create `lessons/02-routing-handoff/invariants.yaml` with IDs `M2-I01` through `M2-I17`, one for each accepted invariant in spec section 17.

- [ ] **Step 7: Run shared contract regression**

Run:

~~~bash
python -m unittest   tools.contracts.test_contracts   tools.contracts.test_m1_contracts   tools.contracts.test_m2_contracts   -v
~~~

Expected: PASS with all M0/M1/M2 contract tests.

- [ ] **Step 8: Commit**

~~~bash
git add   contracts/handoffs/support-handoff.schema.json   contracts/results/handoff-result.schema.json   contracts/events/run-event.schema.json   fixtures/scenarios/support-handoff.yaml   fixtures/fake-model/support-handoff.yaml   fixtures/failures/support-handoff.yaml   lessons/02-routing-handoff/invariants.yaml   tools/contracts/test_m2_contracts.py
git commit -m "test(m2): add canonical handoff contracts and fixtures"
~~~

---

### Task 2: Add TypeScript M2 foundations, confidence policy, and receiver directory

**Files:**
- Create: `lessons/02-routing-handoff/typescript/package.json`
- Create: `lessons/02-routing-handoff/typescript/package-lock.json`
- Create: `lessons/02-routing-handoff/typescript/tsconfig.json`
- Create: `lessons/02-routing-handoff/typescript/src/types.ts`
- Create: `lessons/02-routing-handoff/typescript/src/paths.ts`
- Create: `lessons/02-routing-handoff/typescript/src/schemas.ts`
- Create: `lessons/02-routing-handoff/typescript/src/scenario.ts`
- Create: `lessons/02-routing-handoff/typescript/src/scripted-router.ts`
- Create: `lessons/02-routing-handoff/typescript/src/policy.ts`
- Create: `lessons/02-routing-handoff/typescript/src/receivers.ts`
- Create tests:
  - `test/schemas.test.ts`
  - `test/scenario.test.ts`
  - `test/policy.test.ts`
  - `test/receivers.test.ts`

**Interfaces:**
- Consumes: Task 1 shared contracts/fixtures.
- Produces:
  - `loadScenario(): ScenarioDefinition`
  - `findScenarioCase(scenario, caseId): ScenarioCase`
  - `loadFailureFixtures(): FailureFixtures`
  - `ScriptedRouteProvider.fromFile(): ScriptedRouteProvider`
  - `RouteDecisionProvider.nextDecision(input: RouteDecisionInput): Promise<unknown>`
  - `classifyWithCode(request: string): RouteDecision`
  - `applyConfidencePolicy(decision: RouteDecision): RouteSelection`
  - `createReceiverDirectory(unavailable?: readonly ReceiverName[]): ReceiverDirectory`
  - schema validators used by the runtime.

Use exact public types:

~~~typescript
export type Route = "billing" | "technical" | "general";
export type RouterMode = "code" | "model";
export type ReceiverName =
  | "billing-specialist"
  | "technical-specialist"
  | "general-specialist";
export type PolicyOutcome = "selected" | "fallback";
export type FailureCode =
  | "INVALID_ROUTE_DECISION"
  | "HANDOFF_CONTEXT_INVALID"
  | "HANDOFF_RECEIVER_UNAVAILABLE";

export interface RouteDecision {
  route: Route;
  confidence: number;
}

export interface RouteDecisionInput {
  caseId: string;
  request: string;
}

export interface RouteDecisionProvider {
  nextDecision(input: RouteDecisionInput): Promise<unknown>;
}

export interface RouteSelection {
  proposedRoute: Route;
  selectedRoute: Route;
  confidence: number;
  policyOutcome: PolicyOutcome;
  fallbackApplied: boolean;
  receiver: ReceiverName;
}

export interface ReceiverInput {
  ticket_id: string;
  request_text: string;
}

export interface SenderIntent {
  route: Route;
  confidence: number;
  policy_outcome: PolicyOutcome;
}

export interface HandoffEnvelope {
  schema_version: "1.0";
  handoff_id: string;
  sender: "support-router";
  receiver: ReceiverName;
  sender_intent: SenderIntent;
  receiver_input: ReceiverInput;
}

export interface HandoffResult {
  schema_version: "1.0";
  run_id: string;
  scenario_id: "support-handoff";
  case_id: string;
  router_mode: RouterMode;
  status: "SUCCEEDED" | "FAILED";
  proposed_route: Route | null;
  selected_route: Route | null;
  receiver: ReceiverName | null;
  fallback_applied: boolean;
  specialist_invoked: boolean;
  failure_code: FailureCode | null;
  trace_path: string;
}

export interface ReceiverDefinition {
  name: ReceiverName;
  handle(input: ReceiverInput): Promise<void>;
}

export interface ReceiverDirectory {
  resolve(name: string): ReceiverDefinition | undefined;
}
~~~

- [ ] **Step 1: Write failing foundation tests**

Pin:

~~~typescript
expect(loadScenario().scenario_id).toBe("support-handoff");
expect(findScenarioCase(loadScenario(), "model-low-confidence-fallback")).toMatchObject({
  router_mode: "model",
  expected_proposed_route: "billing",
  expected_confidence: 0.54,
  expected_selected_route: "general",
  expected_receiver: "general-specialist",
  expected_fallback_applied: true,
});
~~~

Schema tests must reject extra receiver-input fields and missing `request_text`.

Failure-loader tests assert exactly two failure records and prove `code-billing-handoff` has no inherited failure injection.

- [ ] **Step 2: Run TypeScript tests and verify RED**

Run:

~~~bash
npm install --prefix lessons/02-routing-handoff/typescript
npm --prefix lessons/02-routing-handoff/typescript test
~~~

Expected: FAIL because M2 source modules do not exist.

- [ ] **Step 3: Create package/config using Lesson 01 versions**

Use package name:

~~~text
@boundrelay/lesson-02-typescript
~~~

Copy the exact dependency/version and strict compiler settings from Lesson 01; do not add dependencies.

- [ ] **Step 4: Implement shared validators and non-coercing fixture loaders**

`schemas.ts` exposes:

~~~typescript
validateRouteDecision(value: unknown): ValidationResult<RouteDecision>
validateHandoff(value: unknown): ValidationResult<HandoffEnvelope>
validateRunEvent(value: unknown): ValidationResult<RunEvent>
validateHandoffResult(value: unknown): ValidationResult<HandoffResult>
~~~

`scenario.ts` rejects malformed fixture values, duplicate case IDs, unknown failure references, unknown receiver names, or extra failure operators. Never coerce strings to numbers or booleans.

- [ ] **Step 5: Implement deterministic code router and scripted model provider**

`classifyWithCode()` remains lesson-local and copies M0's accepted deterministic keyword baseline without importing Lesson 00:

~~~text
billing keywords: charged, charge, invoice, payment, refund, billed
technical keywords: error, crash, cannot log in, can't log in, bug, broken
otherwise: general
confidence: 1.0
~~~

Pin the canonical code-billing cases plus one technical and one general unit case.

`ScriptedRouteProvider` returns exactly one configured raw route decision for a model-mode case; missing/duplicate access raises deterministic `ScriptedRouteError`. It performs no heuristic fallback.

- [ ] **Step 6: Implement confidence policy and mapping**

Pin exact tests:

~~~typescript
expect(applyConfidencePolicy({route: "billing", confidence: 0.80})).toMatchObject({
  proposedRoute: "billing",
  selectedRoute: "billing",
  receiver: "billing-specialist",
  policyOutcome: "selected",
  fallbackApplied: false,
});

expect(applyConfidencePolicy({route: "billing", confidence: 0.79})).toMatchObject({
  proposedRoute: "billing",
  selectedRoute: "general",
  receiver: "general-specialist",
  policyOutcome: "fallback",
  fallbackApplied: true,
});
~~~

Also assert technical/general mapping and that the policy never accepts a model-provided receiver.

- [ ] **Step 7: Implement exactly three deterministic receivers**

`createReceiverDirectory(unavailable = [])` exposes only the three accepted names.

Each `handle()` accepts exactly `ReceiverInput`, performs no model/tool/network work, and resolves successfully.

Tests assert:

- all three receiver names resolve when available;
- an unavailable receiver resolves to `undefined`;
- unknown receiver names resolve to `undefined`;
- no retry or dynamic registration API exists;
- a recording wrapper sees only `ticket_id` and `request_text`.

- [ ] **Step 8: Run TypeScript foundation gate and commit**

Run:

~~~bash
npm --prefix lessons/02-routing-handoff/typescript run typecheck
npm --prefix lessons/02-routing-handoff/typescript test
python -m unittest tools.contracts.test_m2_contracts -v
~~~

Expected: PASS.

Commit:

~~~bash
git add lessons/02-routing-handoff/typescript
git commit -m "feat(m2): add TypeScript handoff foundations"
~~~

---

### Task 3: Implement the TypeScript M2 runtime, handoff lifecycle, and CLI

**Files:**
- Create: `lessons/02-routing-handoff/typescript/src/trace.ts`
- Create: `lessons/02-routing-handoff/typescript/src/runner.ts`
- Create: `lessons/02-routing-handoff/typescript/src/cli.ts`
- Create tests:
  - `test/trace.test.ts`
  - `test/runner.test.ts`
  - `test/cli.test.ts`
  - `test/offline-import-probe.ts`

**Interfaces:**
- Consumes: Task 2 types, validators, fixture loaders, policy, router provider, receiver directory.
- Produces:

~~~typescript
export interface RunScenarioCaseOptions {
  mode: RouterMode;
  caseId: string;
  tracePath: string;
  routeProvider?: RouteDecisionProvider;
  receiverDirectory?: ReceiverDirectory;
  clock?: () => Date;
  idFactory?: () => string;
}

export function runScenarioCase(
  options: RunScenarioCaseOptions,
): Promise<HandoffResult>;
~~~

CLI:

~~~text
npm --prefix lessons/02-routing-handoff/typescript run run --   --mode <code|model>   --case <case-id>   --trace <path>
~~~

- [ ] **Step 1: Write failing canonical success/failure tests**

Pin all five result shapes from Task 1.

For `code-billing-handoff` assert:

- status SUCCEEDED;
- proposed/selected route billing;
- receiver billing-specialist;
- fallback false;
- specialist invoked true;
- zero `model.*` events;
- event order includes `route.selected -> handoff.requested -> handoff.accepted -> run.completed`.

For `model-technical-handoff`, assert one model decision and same handoff lifecycle.

For fallback, assert sender intent route remains billing while selected receiver is general-specialist.

For both canonical handoff failures, assert `handoff.requested -> handoff.rejected -> run.failed`, zero `handoff.accepted`, and zero specialist invocations.

- [ ] **Step 2: Implement strict JSONL trace sink**

Copy the proven Lesson 01 JSON-safe/LF-only behavior into Lesson 02 rather than importing another lesson package.

Every event validates against the shared event schema before storage.

- [ ] **Step 3: Implement route acquisition and fail-closed route validation**

Runtime order:

1. code mode → `classifyWithCode(request)`;
2. model mode → emit `model.requested`, call provider once, emit JSON-safe `model.completed`;
3. validate full route decision;
4. invalid route → emit `route.rejected`, terminate `INVALID_ROUTE_DECISION` before handoff construction.

Add a unit test with malformed model route decision and assert no `handoff.requested` and no receiver resolution/invocation.

Provider fixture/configuration exceptions remain tooling failures; do not invent another M2 result failure code.

- [ ] **Step 4: Implement confidence policy and candidate handoff construction**

After valid route decision:

- apply Task 2 policy;
- emit `route.selected`;
- build candidate envelope with a generated `handoff_id`;
- `sender_intent.route` is the proposed route;
- `receiver` is derived from selected route;
- `receiver_input` begins with exactly ticket ID and request text;
- apply only the named case's failure fixture;
- emit `handoff.requested` before handoff validation.

Use exact payloads:

~~~text
route.selected:
  router_mode
  proposed_route
  selected_route
  confidence
  fallback_applied

handoff.requested:
  handoff_id
  sender
  receiver
  sender_intent
  receiver_input
~~~

- [ ] **Step 5: Implement handoff validation, receiver resolution, and dispatch**

Order:

1. validate candidate handoff;
2. invalid → one `handoff.rejected` with `HANDOFF_CONTEXT_INVALID`;
3. resolve receiver;
4. unavailable → one `handoff.rejected` with `HANDOFF_RECEIVER_UNAVAILABLE`;
5. emit `handoff.accepted`;
6. invoke receiver exactly once;
7. mark `specialist_invoked=true`;
8. terminal success.

No rejection path retries or chooses a second receiver.

Inject a recording receiver directory in tests and assert exact invocation count and exact two-key input.

- [ ] **Step 6: Pin unexpected receiver exception as tooling failure**

Inject a receiver whose `handle()` throws.

Assert the runner rejects rather than returning any accepted M2 domain failure code, and no second receiver invocation occurs.

The CLI must report the exception on stderr and exit `2`.

Do not emit `handoff.rejected` after `handoff.accepted` for this tooling failure.

- [ ] **Step 7: Add lifecycle/trace invariants**

Tests assert:

- stable run ID;
- contiguous sequence numbers;
- exactly one terminal run event for all canonical domain outcomes;
- code mode has no model events;
- invalid route has route.rejected and no handoff events;
- accepted success has requested then accepted;
- rejected handoff has requested then rejected;
- no `step.*` requirement is introduced by M2.

- [ ] **Step 8: Prove all canonical runs are offline**

Use the same proven network-denial strategy from M1: preserve `socket`/Node runtime classes and deny actual AF_INET/AF_INET6/connect/fetch boundaries without breaking local event-loop plumbing.

Run all five canonical cases and a fresh-import probe under the guard.

- [ ] **Step 9: Implement strict CLI**

Accept exactly:

~~~text
--mode
--case
--trace
~~~

Reject duplicates, positional values, missing values, and unknown flags.

Domain failures still print one result JSON line and exit `0`; configuration/tooling failures return `2`.

- [ ] **Step 10: Run TypeScript runtime gate and commit**

~~~bash
npm --prefix lessons/02-routing-handoff/typescript run typecheck
npm --prefix lessons/02-routing-handoff/typescript test
python -m unittest tools.contracts.test_m2_contracts -v
~~~

Expected: PASS.

~~~bash
git add lessons/02-routing-handoff/typescript
git commit -m "feat(m2): implement TypeScript typed handoff runtime"
~~~

---

### Task 4: Add Python M2 foundations, confidence policy, and receiver directory

**Files:**
- Create: `lessons/02-routing-handoff/python/pyproject.toml`
- Create:
  - `src/boundrelay_m2/__init__.py`
  - `src/boundrelay_m2/types.py`
  - `src/boundrelay_m2/paths.py`
  - `src/boundrelay_m2/schemas.py`
  - `src/boundrelay_m2/scenario.py`
  - `src/boundrelay_m2/scripted_router.py`
  - `src/boundrelay_m2/policy.py`
  - `src/boundrelay_m2/receivers.py`
- Create tests:
  - `tests/test_schemas.py`
  - `tests/test_scenario.py`
  - `tests/test_policy.py`
  - `tests/test_receivers.py`

**Interfaces:**
- Consumes: Task 1 assets.
- Produces Python equivalents of all Task 2 interfaces.

Package:

~~~text
project name: boundrelay-m2
import package: boundrelay_m2
Python: >=3.14
dependencies: PyYAML==6.0.3, jsonschema[format]==4.26.0
~~~

Use dataclasses/protocols with the same field names used by shared JSON contracts.

- [ ] **Step 1: Write failing Python foundation tests**

Mirror Task 2 assertions, including:

~~~python
self.assertEqual(apply_confidence_policy(RouteDecision("billing", 0.80)).selected_route, "billing")
self.assertEqual(apply_confidence_policy(RouteDecision("billing", 0.79)).selected_route, "general")
~~~

Fixture tests prove the two failure records are isolated to their named cases.

- [ ] **Step 2: Run and verify RED**

~~~bash
PYTHONPATH=lessons/02-routing-handoff/python/src python -m unittest discover -s lessons/02-routing-handoff/python/tests -v
~~~

Expected: import/module failures because M2 package foundations do not exist.

- [ ] **Step 3: Implement types, paths, schema validation, and non-coercing loaders**

Keep names semantically aligned with TypeScript but idiomatic Python:

~~~python
def load_scenario(...) -> ScenarioDefinition
def find_scenario_case(scenario, case_id) -> ScenarioCase
def load_failure_fixtures(...) -> FailureFixtures
def validate_route_decision(value: object) -> ValidationResult[dict[str, object]]
def validate_handoff(value: object) -> ValidationResult[dict[str, object]]
def validate_run_result(value: object) -> ValidationResult[dict[str, object]]
~~~

Reject unknown failure operators and malformed values; do not coerce.

- [ ] **Step 4: Implement code router and scripted route provider**

Code routing remains lesson-local and deterministic. Copy the same exact keyword baseline pinned in Task 2; do not import `boundrelay_m0`.

Scripted provider exposes:

~~~python
async def next_decision(self, *, case_id: str, request: str) -> object
~~~

A model-mode case may be consumed once; missing or duplicate consumption raises `ScriptedRouteError`.

- [ ] **Step 5: Implement fixed confidence policy**

~~~python
def apply_confidence_policy(decision: RouteDecision) -> RouteSelection
~~~

Pin `0.80` and `0.79`, plus all route-to-receiver mappings.

- [ ] **Step 6: Implement exactly three deterministic receivers**

~~~python
def create_receiver_directory(
    unavailable: tuple[ReceiverName, ...] = (),
) -> ReceiverDirectory
~~~

Receiver handlers are async deterministic no-ops after validated input: they return successfully without model, tool, network, persistence, or side effects. Runtime tests use injected recording receivers to prove invocation count/input.

- [ ] **Step 7: Run Python foundation gate and commit**

~~~bash
PYTHONPATH=lessons/02-routing-handoff/python/src python -m unittest discover -s lessons/02-routing-handoff/python/tests -v
python -m compileall -q lessons/02-routing-handoff/python/src
python -m unittest tools.contracts.test_m2_contracts -v
~~~

Expected: PASS.

~~~bash
git add lessons/02-routing-handoff/python
git commit -m "feat(m2): add Python handoff foundations"
~~~

---

### Task 5: Implement the Python M2 runtime, handoff lifecycle, and CLI

**Files:**
- Create:
  - `lessons/02-routing-handoff/python/src/boundrelay_m2/trace.py`
  - `lessons/02-routing-handoff/python/src/boundrelay_m2/runner.py`
  - `lessons/02-routing-handoff/python/src/boundrelay_m2/cli.py`
  - `lessons/02-routing-handoff/python/src/boundrelay_m2/__main__.py`
- Create:
  - `tests/test_trace.py`
  - `tests/test_runner.py`
  - `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 4 foundations.
- Produces:

~~~python
async def run_scenario_case(
    *,
    mode: RouterMode,
    case_id: str,
    trace_path: str,
    route_provider: RouteDecisionProvider | None = None,
    receiver_directory: ReceiverDirectory | None = None,
    clock: Clock | None = None,
    id_factory: IdFactory | None = None,
) -> HandoffResult
~~~

CLI:

~~~text
python -m boundrelay_m2 --mode <code|model> --case <id> --trace <path>
~~~

- [ ] **Step 1: Write failing mirrored runtime tests**

Mirror every Task 3 canonical result/event assertion.

Use a recording receiver directory to assert successful cases perform exactly one invocation and rejected cases perform zero.

- [ ] **Step 2: Implement strict JSONL trace sink**

Mirror Task 3 observable behavior and Lesson 01 Python strict JSON serialization; do not import another lesson package.

- [ ] **Step 3: Implement route acquisition and validation**

Code mode emits no model events.

Model mode calls the scripted provider once and validates the raw route decision before confidence policy.

Malformed route decision returns `INVALID_ROUTE_DECISION`, emits `route.rejected`, and never emits `handoff.requested`.

- [ ] **Step 4: Implement policy, candidate handoff, failure injection, and handoff events**

Preserve exact payload keys from Task 3.

For context loss, omit only `receiver_input.request_text` before `handoff.requested`.

For receiver unavailable, leave the envelope valid and make only `billing-specialist` unavailable for that named case.

- [ ] **Step 5: Implement receiver dispatch and exact failure semantics**

- invalid envelope → `HANDOFF_CONTEXT_INVALID`;
- unavailable receiver → `HANDOFF_RECEIVER_UNAVAILABLE`;
- accepted success → one receiver invocation;
- no retry or secondary receiver selection.

- [ ] **Step 6: Pin unexpected receiver exception as tooling failure**

Injected receiver exceptions propagate to CLI/tooling error handling and do not become a third canonical handoff failure.

- [ ] **Step 7: Add offline/fresh-import guards**

Use the proven Python 3.14-safe guard pattern from M1:

- keep `socket.socket` as a class;
- deny `socket.create_connection`;
- deny AF_INET/AF_INET6 through `socket.socket.connect`;
- allow AF_UNIX needed by asyncio internals.

Run all five canonical cases under the guard.

- [ ] **Step 8: Implement CLI and module entrypoint**

`__main__.py` calls `main()`.

One compact JSON result line on stdout for domain outcomes; diagnostics on stderr; exit `2` for CLI/tooling failures.

- [ ] **Step 9: Run Python runtime gate and commit**

~~~bash
PYTHONPATH=lessons/02-routing-handoff/python/src python -m unittest discover -s lessons/02-routing-handoff/python/tests -v
python -m compileall -q lessons/02-routing-handoff/python/src
~~~

Expected: PASS.

~~~bash
git add lessons/02-routing-handoff/python
git commit -m "feat(m2): implement Python typed handoff runtime"
~~~

---

### Task 6: Add M2 cross-language parity and revision-bound certification

**Files:**
- Modify: `tools/parity/normalize.py`
- Modify: `tools/parity/test_normalize.py`
- Create: `tools/parity/verify_m2.py`
- Create: `tools/parity/test_m2_verification_safety.py`
- Create: `scripts/verify_m2.py`

**Interfaces:**
- Consumes: both M2 CLIs, Task 1 contracts/fixtures, existing strict JSONL reader.
- Produces:
  - local authority `python scripts/verify_m2.py`;
  - `.boundrelay/m2/traces/*.jsonl`;
  - `.boundrelay/m2/verification-evidence.json`.

- [ ] **Step 1: Write narrow normalization RED test**

Generated `handoff_id` is parity-ignored by the accepted spec.

Add a test proving these two handoff events normalize equal despite different IDs:

~~~python
ts = {
    "type": "handoff.requested",
    "data": {"handoff_id": "ts-1", "receiver": "billing-specialist"},
}
py = {
    "type": "handoff.requested",
    "data": {"handoff_id": "py-9", "receiver": "billing-specialist"},
}
self.assertEqual(normalize_event(ts), normalize_event(py))
~~~

Do not ignore receiver, sender intent, receiver input, route, confidence, failure code, or fallback fields.

- [ ] **Step 2: Implement only M2 handoff-ID normalization**

For event types `handoff.requested|handoff.accepted|handoff.rejected`, copy the event data and remove only top-level `handoff_id` before returning the normalized event.

No other M0/M1 normalizer behavior changes.

- [ ] **Step 3: Write verifier-safety RED tests**

Pin helpers that reject:

- wrong case ID or router mode;
- result trace path different from requested path;
- unstable run IDs;
- non-contiguous sequences;
- more than one terminal event;
- code mode with any model event;
- invalid-route failure with any handoff event;
- context-loss/unavailable failure with `handoff.accepted`;
- rejected handoff with specialist_invoked true;
- successful handoff without exactly requested → accepted lifecycle;
- low-confidence case whose sender intent route is not billing or selected receiver is not general-specialist.

Also test clean-worktree + same-HEAD evidence publication and stale evidence clearing.

- [ ] **Step 4: Implement five-case CLI execution and schema validation**

`tools/parity/verify_m2.py` executes both runtimes for exactly the five canonical case/mode pairs.

Use absolute trace paths when invoking CLIs so `npm --prefix` working-directory behavior cannot relocate traces.

Validate:

- existing route-decision contract for model decisions as observed in trace;
- support handoff candidates where expected valid;
- handoff result contract;
- every event contract.

For the intentional context-loss candidate, validate that it fails the handoff schema exactly because `request_text` is missing.

- [ ] **Step 5: Implement semantic M2 invariant checks**

Per case, assert fixture-defined:

- status/failure;
- proposed route;
- selected route;
- receiver;
- fallback flag;
- specialist invocation;
- model event presence/absence;
- route.selected payload;
- handoff lifecycle;
- sender intent;
- receiver input;
- no-dispatch semantics.

Pin equality/fallback rules independently of the five scenario values with verifier-safety/unit tests.

- [ ] **Step 6: Compare normalized TypeScript/Python behavior**

For every canonical case:

~~~python
self.assertEqual(normalize_result(ts_result), normalize_result(py_result))
self.assertEqual(normalized_trace(ts_trace), normalized_trace(py_trace))
~~~

No language-specific parity exceptions.

- [ ] **Step 7: Implement revision-bound evidence**

Evidence records:

~~~text
schema_version
scenario_id = support-handoff
status = PASSED
revision
command = python scripts/verify_m2.py
runtime versions
five case records
per-case router mode/status/failure/proposed route/selected route/receiver/fallback/specialist invocation
typescript_trace
python_trace
~~~

Require clean worktree before verification and immediately before publication; reject changed HEAD.

- [ ] **Step 8: Implement top-level M2 authority**

`scripts/verify_m2.py` clears `.boundrelay/m2/` before the first command, then runs exactly:

~~~text
python scripts/verify_m1.py
python -m unittest tools.contracts.test_m2_contracts -v
npm --prefix lessons/02-routing-handoff/typescript run typecheck
npm --prefix lessons/02-routing-handoff/typescript test
PYTHONPATH=lessons/02-routing-handoff/python/src python -m unittest discover -s lessons/02-routing-handoff/python/tests -v
python -m unittest tools.parity.test_normalize tools.parity.test_trace_contract tools.parity.test_m2_verification_safety -v
PYTHONPATH=lessons/02-routing-handoff/python/src python -m tools.parity.verify_m2
~~~

M2 does not invoke `verify_m0.py` separately because `verify_m1.py` already owns that lower-milestone regression chain.

- [ ] **Step 9: Run focused dirty-worktree-safe gates and commit**

~~~bash
python -m unittest tools.contracts.test_m2_contracts tools.parity.test_m2_verification_safety -v
npm --prefix lessons/02-routing-handoff/typescript run typecheck
npm --prefix lessons/02-routing-handoff/typescript test
PYTHONPATH=lessons/02-routing-handoff/python/src python -m unittest discover -s lessons/02-routing-handoff/python/tests -v
~~~

Expected: PASS.

~~~bash
git add tools/parity scripts/verify_m2.py
git commit -m "test(m2): add parity and revision-bound verification"
~~~

---

### Task 7: Add Lesson 02 documentation, M2 CI, root status, and final evidence

**Files:**
- Create: `lessons/02-routing-handoff/README.md`
- Create: `.github/workflows/m2.yml`
- Modify: `README.md`
- Modify: `README.tr.md`

**Interfaces:**
- Consumes: completed Tasks 1–6.
- Produces: published Lesson 02, one-command M2 verification, exact-head CI artifact, and repository M2 status.

- [ ] **Step 1: Write Lesson 02 using the foundation lesson contract**

Use exactly these headings:

1. Problem
2. Success criteria
3. Deterministic baseline
4. Reason to introduce model judgment
5. Naive implementation
6. Failure injection
7. Corrected implementation
8. Verification evidence
9. Trade-offs
10. When not to use this pattern
11. Exercises

The lesson must explicitly teach:

~~~text
route decision != handoff authorization
sender intent != receiver input
confidence proposal != fallback policy
named specialist != autonomous agent
~~~

Document all five canonical cases and why receiver agents/retries/persistence are deferred.

- [ ] **Step 2: Add exact-head M2 workflow**

Mirror the hardened M1 workflow:

- `actions/checkout@v7` with exact PR head and `persist-credentials: false`;
- `actions/setup-node@v7`;
- `actions/setup-python@v7`;
- `actions/upload-artifact@v7`;
- marker versions from root files;
- npm cache for Lesson 00/01/02 lockfiles;
- pip cache for requirements + Lesson 00/01/02 pyprojects;
- editable install all three Python lesson packages;
- `npm ci` all three TypeScript lessons;
- execute only `python scripts/verify_m2.py` as the M2 authority;
- upload `.boundrelay/m2/` as `m2-verification-<exact-head-sha>`;
- include hidden files;
- `if-no-files-found: error`;
- retention 14 days;
- workflow timeout 15 minutes.

- [ ] **Step 3: Update root English/Turkish project status**

Change phase/status to M2 complete only after implementation exists.

Preserve M0 and M1 verification instructions, then add M2 setup/authority instructions.

Do not claim multi-agent receivers, retry, persistence, side effects, Go, real providers, MCP, or framework mappings.

- [ ] **Step 4: Commit docs/CI**

~~~bash
git add   lessons/02-routing-handoff/README.md   .github/workflows/m2.yml   README.md   README.tr.md
git commit -m "docs(m2): add handoff lesson and verification workflow"
~~~

- [ ] **Step 5: Run exact-revision certification**

Worktree must be clean.

~~~bash
python scripts/verify_m2.py
~~~

Expected:

- M0/M1 lower authorities pass through `verify_m1.py`;
- M2 shared contracts pass;
- TypeScript typecheck/tests pass;
- Python tests pass;
- parity/safety tests pass;
- five TypeScript/Python canonical runs match;
- `.boundrelay/m2/verification-evidence.json` reports PASSED;
- evidence revision equals `git rev-parse HEAD`.

- [ ] **Step 6: Inspect evidence before review**

~~~bash
git status --short
git rev-parse HEAD
python -m json.tool .boundrelay/m2/verification-evidence.json
~~~

Expected: clean worktree, exact revision match, exactly five case records.

Generated `.boundrelay/` evidence remains untracked/ignored and is never committed.

---

## Dependency Order

~~~text
Task 1  shared contracts / fixtures / invariants
   ↓
Task 2  TypeScript foundations / policy / receivers
   ↓
Task 3  TypeScript runtime / handoff lifecycle
   ↓
Task 4  Python foundations / policy / receivers
   ↓
Task 5  Python runtime / handoff lifecycle
   ↓
Task 6  cross-language parity / revision certification
   ↓
Task 7  documentation / CI / final exact-revision evidence
~~~

Tasks 2–3 and 4–5 are conceptually parallel, but use the order above. The Python track may compare observable choices against the reviewed TypeScript implementation, but TypeScript is not canonical; Task 1 shared assets and the accepted spec remain canonical.

Any contract mismatch discovered later returns to Task 1 assets first, then both language implementations update together.

## Verification Matrix

| Behavior | Shared contract | TS unit/runtime | Python unit/runtime | Cross-language verifier |
|---|---:|---:|---:|---:|
| exact five cases | ✓ | ✓ | ✓ | ✓ |
| M0 route schema reuse | ✓ | ✓ | ✓ | ✓ |
| code mode no model | — | ✓ | ✓ | ✓ |
| 0.80 selected | — | ✓ | ✓ | safety/unit |
| 0.79 fallback | — | ✓ | ✓ | safety/unit |
| proposed vs selected route | ✓ | ✓ | ✓ | ✓ |
| minimum receiver input | ✓ | ✓ | ✓ | ✓ |
| context-loss no dispatch | ✓ | ✓ | ✓ | ✓ |
| unavailable receiver no dispatch | ✓ | ✓ | ✓ | ✓ |
| one invocation on success | — | ✓ | ✓ | ✓ |
| no retry | invariant | ✓ | ✓ | ✓ |
| unexpected receiver exception remains tooling failure | — | ✓ | ✓ | — |
| offline import/runtime | invariant | ✓ | ✓ | CI |
| event schema + terminal integrity | ✓ | ✓ | ✓ | ✓ |
| generated handoff ID ignored only for parity | — | normalize test | normalize test | ✓ |
| exact-revision evidence | — | — | — | ✓ |
| M1 regression authority | — | — | — | ✓ |

## Scope Stop Conditions

Stop implementation and return to D-013 if any task appears to require:

- a fourth receiver;
- a new route beyond billing/technical/general;
- changing the `0.80` confidence threshold or equality semantics;
- a model-backed receiver;
- receiver tool use;
- multiple handoffs in one canonical run;
- retry/backoff;
- persistence/checkpoints/resume;
- side-effecting receiver behavior;
- idempotency or approval;
- parallel fan-out/fan-in;
- Go;
- MCP or framework adapters;
- real provider integration;
- dynamic agent discovery;
- generic agent registry;
- shared runtime extraction from M0/M1/M2;
- a sixth canonical milestone parity case;
- a new canonical M2 handoff failure code;
- modifying the existing M0 route-decision schema to carry M2 handoff fields;
- changing the accepted sender-intent versus receiver-input separation;
- changing the M1→M2 verification authority chain.
