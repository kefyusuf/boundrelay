# M1 Bounded Single-Agent Tool Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the accepted M1 order-investigation lesson as an offline, deterministic, read-only single-agent tool loop with TypeScript/Python behavioral parity, hard budgets, fail-closed tool dispatch, and revision-bound verification.

**Architecture:** Canonical fixtures and JSON Schemas remain language-neutral. Each language gets its own lesson-local implementation of the same observable behavior: direct call baseline, scripted model loop, explicit tool registry, runtime-owned timeout/budget enforcement, strict JSONL trace output, and one JSON result. Shared Python parity tooling executes both CLIs, validates all eight canonical cases, compares normalized traces/results, and publishes evidence bound to the exact Git revision. M0 stays independent; M1 does not extract a reusable runtime from M0.

**Tech Stack:** Node.js 24, TypeScript 7.0.2, tsx 4.23.13, Vitest 4.1.7, Ajv 8.20.0, ajv-formats 3.0.1, yaml 2.9.0, Python 3.14, PyYAML 6.0.3, jsonschema 4.26.0, Python unittest, JSON Schema Draft 2020-12, GitHub Actions v7.

**Spec:** `docs/superpowers/specs/2026-09-15-m1-bounded-tool-loop-design.md`

## Global Constraints

- M1 contains exactly the eight accepted `order-investigation` parity cases; do not add a ninth milestone trajectory.
- The only registered M1 tools are `lookup_order` and `lookup_shipment`; both are `READ_ONLY`.
- Direct mode never invokes a model and consumes zero model steps and zero model tokens.
- Agent mode uses a deterministic offline scripted model; no real provider, API key, network call, tokenizer dependency, or framework adapter is added.
- The outer model-turn schema validates structure but deliberately does **not** enumerate tool names; registry lookup owns `UNKNOWN_TOOL`.
- Tool argument schemas require exactly one identifier field and reject additional properties: `order_id` matches `^ORD-[0-9]{4}$`, `shipment_id` matches `^SHP-[0-9]{4}$`.
- Validation order is fixed: model-turn shape → usage accounting → token budget → final/tool branch → registry → tool arguments → continuation/step budget → timeout-bound dispatch.
- `max_steps` counts model turns. A final answer on the last permitted turn is valid; a tool call on that turn fails with `STEP_BUDGET_EXCEEDED` before dispatch.
- Token equality is valid; only `tokens_used > max_tokens` fails. An over-budget turn cannot dispatch a tool or be accepted as a final answer.
- Timeout and tool execution failure are single-attempt failures; M1 performs no automatic retry.
- `UNKNOWN` is not an M1 result status because all tools are read-only.
- The shared event envelope remains schema version `1.0`; M1 adds only `tool.requested`, `tool.completed`, `tool.failed`, `budget.consumed`, and `budget.exceeded` to the existing event enum.
- M1 trace payloads record observable decisions/actions/results only; no private chain-of-thought fields are introduced.
- TypeScript and Python are behaviorally equivalent but may remain idiomatic internally; neither language is canonical.
- M0 must remain green. Do not move M0 code into M1 or extract a shared runtime package during this milestone.
- Node floor remains `24`; Python floor remains `3.14`; do not add third-party dependencies beyond the versions already used by M0.

## Review Focus

1. **Structurally invalid model turn:** return `FAILED / INVALID_MODEL_DECISION`, emit no tool request, and do not count unvalidated usage.
2. **Budget equality boundaries:** `model_steps == max_steps` may still produce a final answer; `tokens_used == max_tokens` is valid.
3. **Rejected continuation after prior success:** the step-budget and token-budget cases may have one earlier successful tool invocation, but the rejected later decision must cause no additional invocation.
4. **Direct-path tool failure:** direct mode must use the same timeout/execution boundary as agent mode while still emitting no model events.
5. **Scripted trajectory exhaustion/out-of-order access:** fail deterministically as `INVALID_MODEL_DECISION`; never fall back to heuristics or another trajectory.

## Planned File Map

```text
contracts/
├── agent/model-turn.schema.json
├── tools/lookup-order-arguments.schema.json
├── tools/lookup-shipment-arguments.schema.json
├── results/tool-loop-result.schema.json
└── events/run-event.schema.json                  # extend enum only

fixtures/
├── scenarios/order-investigation.yaml
├── fake-model/order-investigation.yaml
└── fake-tools/order-investigation.yaml

lessons/01-bounded-tool-loop/
├── README.md
├── invariants.yaml
├── typescript/
│   ├── package.json
│   ├── package-lock.json
│   ├── tsconfig.json
│   ├── src/
│   │   ├── cli.ts
│   │   ├── executor.ts
│   │   ├── fake-tools.ts
│   │   ├── paths.ts
│   │   ├── runner.ts
│   │   ├── scenario.ts
│   │   ├── schemas.ts
│   │   ├── scripted-model.ts
│   │   ├── tool-registry.ts
│   │   ├── trace.ts
│   │   └── types.ts
│   └── test/
│       ├── cli.test.ts
│       ├── offline-import-probe.ts
│       ├── runner.test.ts
│       ├── scenario.test.ts
│       ├── schemas.test.ts
│       ├── tools.test.ts
│       └── trace.test.ts
└── python/
    ├── pyproject.toml
    ├── src/boundrelay_m1/
    │   ├── __init__.py
    │   ├── __main__.py
    │   ├── cli.py
    │   ├── executor.py
    │   ├── fake_tools.py
    │   ├── paths.py
    │   ├── runner.py
    │   ├── scenario.py
    │   ├── schemas.py
    │   ├── scripted_model.py
    │   ├── tool_registry.py
    │   ├── trace.py
    │   └── types.py
    └── tests/
        ├── test_cli.py
        ├── test_runner.py
        ├── test_scenario.py
        ├── test_schemas.py
        ├── test_tools.py
        └── test_trace.py

tools/contracts/test_m1_contracts.py
tools/parity/verify_m1.py
tools/parity/test_m1_verification_safety.py
scripts/verify_m1.py
.github/workflows/m1.yml
README.md
README.tr.md
```

---

### Task 1: Add canonical M1 fixtures and shared contracts

**Files:**
- Create: `contracts/agent/model-turn.schema.json`
- Create: `contracts/tools/lookup-order-arguments.schema.json`
- Create: `contracts/tools/lookup-shipment-arguments.schema.json`
- Create: `contracts/results/tool-loop-result.schema.json`
- Modify: `contracts/events/run-event.schema.json`
- Create: `fixtures/scenarios/order-investigation.yaml`
- Create: `fixtures/fake-model/order-investigation.yaml`
- Create: `fixtures/fake-tools/order-investigation.yaml`
- Create: `lessons/01-bounded-tool-loop/invariants.yaml`
- Create: `tools/contracts/test_m1_contracts.py`

**Interfaces:**
- Consumes: accepted M1 design and existing Draft 2020-12 event envelope.
- Produces: the eight case IDs, exact budgets/outcomes, model-turn contract, two tool-argument contracts, M1 result contract, fake trajectories/tool records, and M1-I01 through M1-I14 invariants used by every later task.

- [ ] **Step 1: Write failing canonical-asset tests**

Create `tools/contracts/test_m1_contracts.py` with tests that pin the case set and key boundary values:

```python
EXPECTED_CASES = {
    "direct-order-status",
    "agent-delayed-shipment",
    "agent-unknown-tool",
    "agent-invalid-arguments",
    "agent-tool-timeout",
    "agent-tool-failure",
    "agent-step-budget",
    "agent-token-budget",
}

def test_m1_case_set_and_success_boundaries(self) -> None:
    scenario = load_yaml(SCENARIO)
    cases = {case["id"]: case for case in scenario["cases"]}
    self.assertEqual(set(cases), EXPECTED_CASES)
    self.assertEqual(cases["direct-order-status"]["mode"], "direct")
    self.assertEqual(cases["direct-order-status"]["max_steps"], 0)
    self.assertEqual(cases["direct-order-status"]["max_tokens"], 0)
    self.assertEqual(cases["agent-delayed-shipment"]["max_steps"], 3)
    self.assertEqual(cases["agent-delayed-shipment"]["max_tokens"], 129)
    self.assertEqual(cases["agent-delayed-shipment"]["expected_model_steps"], 3)
    self.assertEqual(cases["agent-delayed-shipment"]["expected_tokens_used"], 129)
    self.assertEqual(cases["agent-delayed-shipment"]["expected_tool_invocations"], 2)

def test_budget_failures_preserve_one_prior_dispatch(self) -> None:
    scenario = load_yaml(SCENARIO)
    cases = {case["id"]: case for case in scenario["cases"]}
    self.assertEqual(cases["agent-step-budget"]["expected_tool_invocations"], 1)
    self.assertEqual(cases["agent-token-budget"]["expected_tool_invocations"], 1)
    self.assertEqual(cases["agent-step-budget"]["expected_failure_code"], "STEP_BUDGET_EXCEEDED")
    self.assertEqual(cases["agent-token-budget"]["expected_failure_code"], "TOKEN_BUDGET_EXCEEDED")
```

- [ ] **Step 2: Run the contract test and confirm it fails**

Run:

```bash
python -m unittest tools.contracts.test_m1_contracts -v
```

Expected: FAIL because the M1 fixture/schema files do not exist.

- [ ] **Step 3: Add the exact canonical scenario values**

Create `fixtures/scenarios/order-investigation.yaml` with `schema_version: "1.0"`, `scenario_id: order-investigation`, and these fixed case facts:

| Case | mode | max_steps | max_tokens | model_steps | tokens_used | tool_invocations | outcome |
|---|---:|---:|---:|---:|---:|---:|---|
| direct-order-status | direct | 0 | 0 | 0 | 0 | 1 | exact direct answer |
| agent-delayed-shipment | agent | 3 | 129 | 3 | 129 | 2 | exact agent answer |
| agent-unknown-tool | agent | 2 | 100 | 1 | 25 | 0 | UNKNOWN_TOOL |
| agent-invalid-arguments | agent | 2 | 100 | 1 | 25 | 0 | INVALID_TOOL_ARGUMENTS |
| agent-tool-timeout | agent | 2 | 100 | 1 | 25 | 1 | TOOL_TIMEOUT |
| agent-tool-failure | agent | 2 | 100 | 1 | 25 | 1 | TOOL_EXECUTION_FAILED |
| agent-step-budget | agent | 2 | 100 | 2 | 50 | 1 | STEP_BUDGET_EXCEEDED |
| agent-token-budget | agent | 3 | 70 | 2 | 75 | 1 | TOKEN_BUDGET_EXCEEDED |

The direct case must contain:

```yaml
direct_call:
  tool: lookup_order
  arguments: {order_id: ORD-1001}
expected_answer: "Order ORD-1001 status is SHIPPED."
```

The agent success case expected answer must be exactly:

```text
Order ORD-1001 is delayed because shipment SHP-1001 is delayed by weather.
```

- [ ] **Step 4: Add deterministic model and tool fixtures**

`fixtures/fake-model/order-investigation.yaml` uses ordered `trajectories`; direct mode has no trajectory. Pin these usage totals and decisions:

- success: `lookup_order ORD-1001` usage 60 → `lookup_shipment SHP-1001` usage 40 → final usage 29;
- unknown tool: one valid outer turn naming `lookup_customer`, usage 25;
- invalid arguments: one `lookup_order` call with `order_id: "1001"`, usage 25;
- timeout: one `lookup_order ORD-9001`, usage 25;
- tool failure: one `lookup_order ORD-9002`, usage 25;
- step budget: `lookup_order ORD-1001` usage 25, then `lookup_shipment SHP-1001` usage 25;
- token budget: `lookup_order ORD-1001` usage 50, then `lookup_shipment SHP-1001` usage 25.

Use stable call IDs `call-1`, `call-2`.

`fixtures/fake-tools/order-investigation.yaml` must define:

```yaml
orders:
  ORD-1001:
    output: {order_id: ORD-1001, status: SHIPPED, shipment_id: SHP-1001}
  ORD-9001:
    behavior: timeout
  ORD-9002:
    behavior: failure
shipments:
  SHP-1001:
    output: {shipment_id: SHP-1001, status: DELAYED, reason: WEATHER}
```

- [ ] **Step 5: Define and test the JSON Schemas**

Add a local test helper `schema_errors(path: Path, value: object) -> list[ValidationError]` that loads JSON and returns `list(Draft202012Validator(schema).iter_errors(value))`. Call `Draft202012Validator.check_schema()` for every new/modified schema, then pin these assertions:

```python
unknown_tool_turn = {
    "schema_version": "1.0",
    "decision": {
        "kind": "tool_call",
        "call_id": "call-1",
        "tool": "unknown-but-structurally-valid",
        "arguments": {},
    },
    "usage": {"input_tokens": 1, "output_tokens": 0},
}
self.assertEqual(schema_errors(MODEL_TURN_SCHEMA, unknown_tool_turn), [])
self.assertNotEqual(schema_errors(LOOKUP_ORDER_SCHEMA, {"order_id": "1001"}), [])
self.assertNotEqual(
    schema_errors(LOOKUP_ORDER_SCHEMA, {"order_id": "ORD-1001", "extra": True}),
    [],
)
self.assertEqual(schema_errors(LOOKUP_ORDER_SCHEMA, {"order_id": "ORD-1001"}), [])
self.assertEqual(schema_errors(LOOKUP_SHIPMENT_SCHEMA, {"shipment_id": "SHP-1001"}), [])
```

Schema requirements:

- model turn uses `oneOf` for `tool_call` versus `final`, rejects additional properties at every object boundary, requires non-negative integer usage, and leaves `decision.tool` as non-empty string;
- M1 result modes are `direct|agent`, statuses `SUCCEEDED|FAILED`, and failure enum is exactly the six canonical failures plus `INVALID_MODEL_DECISION`;
- success requires non-empty `answer` and null `failure_code`; failure requires null `answer` and non-null `failure_code`;
- counters are non-negative integers;
- event schema keeps envelope `1.0` and only expands the type enum with the five accepted M1 event types.

Also assert an existing M0 event still validates after the enum change.

- [ ] **Step 6: Add M1-I01 through M1-I14 and run contract tests**

Encode the fourteen accepted invariants from spec section 18 verbatim in `lessons/01-bounded-tool-loop/invariants.yaml`.

Run:

```bash
python -m unittest tools.contracts.test_contracts tools.contracts.test_m1_contracts -v
```

Expected: PASS; M0 contract tests remain green.

- [ ] **Step 7: Commit**

```bash
git add contracts fixtures lessons/01-bounded-tool-loop/invariants.yaml tools/contracts/test_m1_contracts.py
git commit -m "test(contracts): add canonical M1 tool-loop assets"
```

---

### Task 2: Build the TypeScript M1 domain, fixture loaders, and read-only tool registry

**Files:**
- Create: `lessons/01-bounded-tool-loop/typescript/package.json`
- Create: `lessons/01-bounded-tool-loop/typescript/package-lock.json`
- Create: `lessons/01-bounded-tool-loop/typescript/tsconfig.json`
- Create: `lessons/01-bounded-tool-loop/typescript/src/types.ts`
- Create: `lessons/01-bounded-tool-loop/typescript/src/paths.ts`
- Create: `lessons/01-bounded-tool-loop/typescript/src/schemas.ts`
- Create: `lessons/01-bounded-tool-loop/typescript/src/scenario.ts`
- Create: `lessons/01-bounded-tool-loop/typescript/src/scripted-model.ts`
- Create: `lessons/01-bounded-tool-loop/typescript/src/fake-tools.ts`
- Create: `lessons/01-bounded-tool-loop/typescript/src/tool-registry.ts`
- Create: `lessons/01-bounded-tool-loop/typescript/test/schemas.test.ts`
- Create: `lessons/01-bounded-tool-loop/typescript/test/scenario.test.ts`
- Create: `lessons/01-bounded-tool-loop/typescript/test/tools.test.ts`

**Interfaces:**
- Consumes: Task 1 contracts/fixtures.
- Produces:
  - `loadScenario(): ScenarioDefinition`
  - `findScenarioCase(scenario: ScenarioDefinition, caseId: string): ScenarioCase`
  - `ScriptedModelProvider.fromFile(): ScriptedModelProvider`
  - `ModelProvider.nextTurn(input: ModelInput): Promise<unknown>`
  - `createFakeToolRegistry(): ToolRegistry`
  - `ToolRegistry.resolve(name: string): ToolDefinition | undefined`
  - shared validators used by the TypeScript runner.

Define these core TypeScript types exactly:

```typescript
export type RunMode = "direct" | "agent";
export type RunStatus = "SUCCEEDED" | "FAILED";
export type ToolName = "lookup_order" | "lookup_shipment";
export type ToolSideEffect = "READ_ONLY";
export type FailureCode =
  | "UNKNOWN_TOOL"
  | "INVALID_TOOL_ARGUMENTS"
  | "TOOL_TIMEOUT"
  | "TOOL_EXECUTION_FAILED"
  | "STEP_BUDGET_EXCEEDED"
  | "TOKEN_BUDGET_EXCEEDED"
  | "INVALID_MODEL_DECISION";

export interface ModelInput {
  caseId: string;
  request: string;
  modelStep: number;
  observations: readonly ToolObservation[];
}

export interface ModelProvider {
  nextTurn(input: ModelInput): Promise<unknown>;
}

export interface ToolDefinition {
  name: ToolName;
  sideEffect: "READ_ONLY";
  timeoutMs: number;
  validateArguments(value: unknown): ValidationResult<Record<string, unknown>>;
  invoke(argumentsValue: Record<string, unknown>): Promise<Record<string, unknown>>;
}

export interface ToolRegistry {
  resolve(name: string): ToolDefinition | undefined;
}
```

- [ ] **Step 1: Add package configuration and failing domain tests**

Use the same dependency versions and strict compiler options as Lesson 00. Package name is `@boundrelay/lesson-01-typescript`; scripts are `typecheck`, `test`, and `run`.

Tests must assert:

```typescript
expect(loadScenario().scenario_id).toBe("order-investigation");
expect(findScenarioCase(loadScenario(), "agent-delayed-shipment")).toMatchObject({
  mode: "agent",
  max_steps: 3,
  max_tokens: 129,
});
expect(validateModelTurn({
  schema_version: "1.0",
  decision: {kind: "tool_call", call_id: "call-1", tool: "unknown-tool", arguments: {}},
  usage: {input_tokens: 1, output_tokens: 0},
}).ok).toBe(true);
```

Run:

```bash
npm install --prefix lessons/01-bounded-tool-loop/typescript
npm --prefix lessons/01-bounded-tool-loop/typescript test
```

Expected: FAIL because source modules do not exist.

- [ ] **Step 2: Implement schema/scenario loaders**

`schemas.ts` exposes:

```typescript
validateModelTurn(value: unknown): ValidationResult<ModelTurn>
validateRunEvent(value: unknown): ValidationResult<RunEvent>
validateRunResult(value: unknown): ValidationResult<RunResult>
validateToolArguments(name: ToolName, value: unknown): ValidationResult<Record<string, unknown>>
```

Use Ajv 2020 with formats; load shared schema files through `paths.ts`.

`scenario.ts` must reject unknown case IDs and malformed loaded scenario values instead of coercing them.

- [ ] **Step 3: Implement the scripted model provider**

`ScriptedModelProvider.nextTurn()` consumes exactly the trajectory element whose one-based position equals `input.modelStep`. A missing trajectory, missing turn, duplicate/out-of-order request, or a request after trajectory exhaustion throws `ScriptedModelError`; it never chooses another case or fabricates a turn.

Add tests that call step 2 before step 1 and request one step beyond the trajectory; both must throw `ScriptedModelError`.

- [ ] **Step 4: Implement the explicit read-only registry**

`createFakeToolRegistry()` registers exactly two definitions, each with `sideEffect: "READ_ONLY"` and `timeoutMs: 100`.

Tests:

```typescript
const registry = createFakeToolRegistry();
expect(registry.resolve("lookup_order")?.sideEffect).toBe("READ_ONLY");
expect(registry.resolve("lookup_shipment")?.sideEffect).toBe("READ_ONLY");
expect(registry.resolve("lookup_customer")).toBeUndefined();
expect(registry.resolve("lookup_order")?.validateArguments({order_id: "ORD-1001"}).ok).toBe(true);
expect(registry.resolve("lookup_order")?.validateArguments({order_id: "1001"}).ok).toBe(false);
```

The fake implementations return the Task 1 outputs; `ORD-9001` never resolves and `ORD-9002` throws a deterministic error.

- [ ] **Step 5: Run TypeScript foundation checks**

```bash
npm --prefix lessons/01-bounded-tool-loop/typescript run typecheck
npm --prefix lessons/01-bounded-tool-loop/typescript test
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add lessons/01-bounded-tool-loop/typescript
git commit -m "feat(m1): add TypeScript tool-loop foundations"
```

---

### Task 3: Implement the TypeScript direct path and bounded agent loop

**Files:**
- Create: `lessons/01-bounded-tool-loop/typescript/src/trace.ts`
- Create: `lessons/01-bounded-tool-loop/typescript/src/executor.ts`
- Create: `lessons/01-bounded-tool-loop/typescript/src/runner.ts`
- Create: `lessons/01-bounded-tool-loop/typescript/src/cli.ts`
- Create: `lessons/01-bounded-tool-loop/typescript/test/trace.test.ts`
- Create: `lessons/01-bounded-tool-loop/typescript/test/runner.test.ts`
- Create: `lessons/01-bounded-tool-loop/typescript/test/cli.test.ts`
- Create: `lessons/01-bounded-tool-loop/typescript/test/offline-import-probe.ts`

**Interfaces:**
- Consumes: Task 2 model provider, registry, validators, scenario types.
- Produces:
  - `invokeTool(definition: ToolDefinition, argumentsValue: Record<string, unknown>): Promise<Record<string, unknown>>`
  - `runScenarioCase(options: RunScenarioCaseOptions): Promise<RunResult>`
  - CLI: `npm --prefix lessons/01-bounded-tool-loop/typescript run run -- --mode <direct|agent> --case <id> --trace <path>`.

`RunScenarioCaseOptions`:

```typescript
export interface RunScenarioCaseOptions {
  mode: RunMode;
  caseId: string;
  tracePath: string;
  modelProvider?: ModelProvider;
  toolRegistry?: ToolRegistry;
  clock?: () => Date;
  idFactory?: () => string;
}
```

- [ ] **Step 1: Write failing direct/success tests**

Pin the direct baseline and successful agent loop:

```typescript
expect(directResult).toMatchObject({
  status: "SUCCEEDED",
  answer: "Order ORD-1001 status is SHIPPED.",
  failure_code: null,
  model_steps: 0,
  tokens_used: 0,
  tool_invocations: 1,
});

expect(agentResult).toMatchObject({
  status: "SUCCEEDED",
  answer: "Order ORD-1001 is delayed because shipment SHP-1001 is delayed by weather.",
  failure_code: null,
  model_steps: 3,
  tokens_used: 129,
  tool_invocations: 2,
});
```

Direct trace must contain zero `model.*` events. Agent trace must show tool order `lookup_order`, then `lookup_shipment`, then terminal success.

Use a recording injected provider to assert model turn 2 receives the `lookup_order` observation and turn 3 receives the shipment observation.

- [ ] **Step 2: Implement strict trace writing**

Follow the Lesson 00 trace safety pattern inside Lesson 01; do not import Lesson 00 runtime code.

`MemoryEventSink.emit(type, data)` must schema-validate every event, keep contiguous `1..N` sequence numbers, sanitize non-JSON values before storage, and `writeJsonl()` must produce UTF-8 LF-delimited strict JSON.

Tests must include a model turn containing BigInt in nested untrusted data and confirm the trace remains strict JSON rather than crashing or serializing a non-standard value.

- [ ] **Step 3: Implement runtime-owned tool execution**

`invokeTool()` uses only standard Node APIs. It races the tool invocation against the definition's 100 ms timeout and maps:

- timeout → `ToolTimeoutError`;
- any other tool exception → `ToolExecutionError`.

The runner increments `tool_invocations` immediately before the actual invoke attempt. Validation/budget rejection never increments it.

- [ ] **Step 4: Implement fixed validation/budget order in `runner.ts`**

For every agent turn:

1. reject before model request if no model turn remains;
2. emit `model.requested`, increment `model_steps`, call provider;
3. emit sanitized `model.completed`;
4. validate the outer turn; invalid → `INVALID_MODEL_DECISION`, no usage counted;
5. add usage and emit one `budget.consumed` carrying both step/token consumed+limits;
6. if token total is over limit, emit `budget.exceeded` with `budget: "token"` and fail;
7. accept final if valid;
8. for tool call: registry lookup → argument validation → continuation budget check;
9. on last permitted model turn, emit `budget.exceeded` with `budget: "step"` and fail before `tool.requested`;
10. emit `tool.requested`, invoke once through timeout boundary, then `tool.completed` or `tool.failed`;
11. append the structured observation and continue.

Provider trajectory errors are caught at the model boundary, emit `model.failed`, and return `FAILED / INVALID_MODEL_DECISION`.

- [ ] **Step 5: Add all failure and boundary tests**

Use `it.each` for the six canonical failures and assert exact result counters from Task 1.

Additional Review Focus tests:

```typescript
expect(agentSuccess.status).toBe("SUCCEEDED");
expect(agentSuccess.model_steps).toBe(3);   // exactly max_steps
expect(agentSuccess.tokens_used).toBe(129); // exactly max_tokens
expect(stepBudgetResult.tool_invocations).toBe(1);
expect(tokenBudgetResult.tool_invocations).toBe(1);
expect(stepBudgetEvents.filter((event) => event.type === "tool.requested")).toHaveLength(1);
expect(tokenBudgetEvents.filter((event) => event.type === "tool.requested")).toHaveLength(1);
expect(invalidModelResult).toMatchObject({
  status: "FAILED",
  failure_code: "INVALID_MODEL_DECISION",
  tool_invocations: 0,
});
```

Inject a direct-mode registry whose `lookup_order` never resolves and assert `TOOL_TIMEOUT`, one attempted invocation, and zero model events.

- [ ] **Step 6: Prove canonical TypeScript execution is offline**

Before importing the runner in `runner.test.ts`, stub both `net.Socket.prototype.connect` and global `fetch` to throw. The dedicated `offline-import-probe.ts` must prove the guard itself fires before application imports.

Run all eight canonical cases under the guard.

- [ ] **Step 7: Implement and test the CLI**

`cli.ts` requires exactly `--mode`, `--case`, and `--trace`, rejects duplicates/unknown options, and prints exactly one compact JSON result line to stdout. Diagnostics go to stderr and exit code `2`.

The requested mode must match the canonical case's mode; mismatch is a CLI/configuration error, not a new parity failure case.

- [ ] **Step 8: Run TypeScript checks and commit**

```bash
npm --prefix lessons/01-bounded-tool-loop/typescript run typecheck
npm --prefix lessons/01-bounded-tool-loop/typescript test
git add lessons/01-bounded-tool-loop/typescript
git commit -m "feat(m1): implement TypeScript bounded tool loop"
```

---

### Task 4: Build the Python M1 domain, fixture loaders, and read-only tool registry

**Files:**
- Create: `lessons/01-bounded-tool-loop/python/pyproject.toml`
- Create: `lessons/01-bounded-tool-loop/python/src/boundrelay_m1/__init__.py`
- Create: `lessons/01-bounded-tool-loop/python/src/boundrelay_m1/__main__.py`
- Create: `lessons/01-bounded-tool-loop/python/src/boundrelay_m1/types.py`
- Create: `lessons/01-bounded-tool-loop/python/src/boundrelay_m1/paths.py`
- Create: `lessons/01-bounded-tool-loop/python/src/boundrelay_m1/schemas.py`
- Create: `lessons/01-bounded-tool-loop/python/src/boundrelay_m1/scenario.py`
- Create: `lessons/01-bounded-tool-loop/python/src/boundrelay_m1/scripted_model.py`
- Create: `lessons/01-bounded-tool-loop/python/src/boundrelay_m1/fake_tools.py`
- Create: `lessons/01-bounded-tool-loop/python/src/boundrelay_m1/tool_registry.py`
- Create: `lessons/01-bounded-tool-loop/python/tests/test_schemas.py`
- Create: `lessons/01-bounded-tool-loop/python/tests/test_scenario.py`
- Create: `lessons/01-bounded-tool-loop/python/tests/test_tools.py`

**Interfaces:**
- Consumes: Task 1 assets.
- Produces the Python equivalents of Task 2 with package name `boundrelay-m1` and import package `boundrelay_m1`.

Use:

```python
class ModelProvider(Protocol):
    async def next_turn(
        self,
        *,
        case_id: str,
        request: str,
        model_step: int,
        observations: tuple[ToolObservation, ...],
    ) -> object: ...

@dataclass(frozen=True)
class ToolDefinition:
    name: ToolName
    side_effect: Literal["READ_ONLY"]
    timeout_ms: int
    validate_arguments: Callable[[object], ValidationResult]
    invoke: Callable[[dict[str, object]], Awaitable[dict[str, object]]]

class ToolRegistry(Protocol):
    def resolve(self, name: str) -> ToolDefinition | None: ...
```

- [ ] **Step 1: Add Python package configuration and failing tests**

`pyproject.toml` uses Python `>=3.14` and the exact PyYAML/jsonschema versions already used by M0.

Pin the same observable boundaries explicitly:

```python
scenario = load_scenario()
case = find_scenario_case(scenario, "agent-delayed-shipment")
self.assertEqual(case.mode, "agent")
self.assertEqual(case.max_steps, 3)
self.assertEqual(case.max_tokens, 129)

unknown_turn = {
    "schema_version": "1.0",
    "decision": {
        "kind": "tool_call",
        "call_id": "call-1",
        "tool": "unknown-tool",
        "arguments": {},
    },
    "usage": {"input_tokens": 1, "output_tokens": 0},
}
self.assertTrue(validate_model_turn(unknown_turn).ok)

registry = create_fake_tool_registry()
self.assertEqual(registry.resolve("lookup_order").side_effect, "READ_ONLY")
self.assertEqual(registry.resolve("lookup_shipment").side_effect, "READ_ONLY")
self.assertIsNone(registry.resolve("lookup_customer"))
self.assertTrue(validate_tool_arguments("lookup_order", {"order_id": "ORD-1001"}).ok)
self.assertFalse(validate_tool_arguments("lookup_order", {"order_id": "1001"}).ok)
```

Run:

```bash
PYTHONPATH=lessons/01-bounded-tool-loop/python/src python -m unittest discover -s lessons/01-bounded-tool-loop/python/tests -v
```

Expected: FAIL because source modules do not exist.

- [ ] **Step 2: Implement schema/scenario loaders**

Expose:

```python
validate_model_turn(value: object) -> ValidationResult
validate_run_event(value: object) -> ValidationResult
validate_run_result(value: object) -> ValidationResult
validate_tool_arguments(name: ToolName, value: object) -> ValidationResult
load_scenario() -> ScenarioDefinition
find_scenario_case(scenario: ScenarioDefinition, case_id: str) -> ScenarioCase
```

No coercion of malformed fixture values.

- [ ] **Step 3: Implement `ScriptedModelProvider`**

`next_turn()` enforces exact one-based model-step order per case. Missing/out-of-order/exhausted access raises `ScriptedModelError`.

Tests mirror the TypeScript out-of-order and exhaustion cases.

- [ ] **Step 4: Implement the read-only tool registry**

`create_fake_tool_registry()` exposes only the two accepted tools, both with 100 ms timeout. Fake tool functions are async:

- normal records return exact structured outputs;
- timeout record awaits indefinitely until the runtime cancels it;
- failure record raises a deterministic exception.

- [ ] **Step 5: Run Python foundation checks and commit**

```bash
PYTHONPATH=lessons/01-bounded-tool-loop/python/src python -m unittest discover -s lessons/01-bounded-tool-loop/python/tests -v

git add lessons/01-bounded-tool-loop/python
git commit -m "feat(m1): add Python tool-loop foundations"
```

---

### Task 5: Implement the Python direct path and bounded agent loop

**Files:**
- Create: `lessons/01-bounded-tool-loop/python/src/boundrelay_m1/trace.py`
- Create: `lessons/01-bounded-tool-loop/python/src/boundrelay_m1/executor.py`
- Create: `lessons/01-bounded-tool-loop/python/src/boundrelay_m1/runner.py`
- Create: `lessons/01-bounded-tool-loop/python/src/boundrelay_m1/cli.py`
- Create: `lessons/01-bounded-tool-loop/python/tests/test_trace.py`
- Create: `lessons/01-bounded-tool-loop/python/tests/test_runner.py`
- Create: `lessons/01-bounded-tool-loop/python/tests/test_cli.py`

**Interfaces:**
- Consumes: Task 4 domain/tool layer.
- Produces:
  - `async def invoke_tool(definition: ToolDefinition, arguments_value: dict[str, object]) -> dict[str, object]`
  - `run_scenario_case(*, mode, case_id, trace_path, model_provider, tool_registry, clock, id_factory) -> Awaitable[RunResult]`
  - CLI: `python -m boundrelay_m1 --mode <direct|agent> --case <id> --trace <path>`.

Use this runner signature:

```python
async def run_scenario_case(
    *,
    mode: RunMode,
    case_id: str,
    trace_path: str,
    model_provider: ModelProvider | None = None,
    tool_registry: ToolRegistry | None = None,
    clock: Clock | None = None,
    id_factory: IdFactory | None = None,
) -> RunResult: ...
```

- [ ] **Step 1: Write failing direct and successful-agent tests**

Pin the result values directly:

```python
self.assertEqual(direct_result.status, "SUCCEEDED")
self.assertEqual(direct_result.answer, "Order ORD-1001 status is SHIPPED.")
self.assertEqual(direct_result.model_steps, 0)
self.assertEqual(direct_result.tokens_used, 0)
self.assertEqual(direct_result.tool_invocations, 1)

self.assertEqual(agent_result.status, "SUCCEEDED")
self.assertEqual(
    agent_result.answer,
    "Order ORD-1001 is delayed because shipment SHP-1001 is delayed by weather.",
)
self.assertEqual(agent_result.model_steps, 3)
self.assertEqual(agent_result.tokens_used, 129)
self.assertEqual(agent_result.tool_invocations, 2)
```

Also assert zero `model.*` events on direct mode, tool order `lookup_order -> lookup_shipment` in agent mode, exactly one terminal event, and that a recording provider receives the order observation on model turn 2 and shipment observation on model turn 3.

- [ ] **Step 2: Implement strict Python trace writing**

Follow the M0 Python trace safety behavior locally in `boundrelay_m1`: sanitize non-finite/non-JSON values before storage and serialize with strict JSON semantics. Do not import `boundrelay_m0`.

Add a test with nested `float("nan")` in untrusted model data and confirm the trace parses with `json.loads(..., parse_constant=reject_constant)`.

- [ ] **Step 3: Implement runtime-owned async timeout**

`invoke_tool()` uses `asyncio.wait_for()` with the definition's 100 ms timeout and maps timeout versus ordinary tool exception to distinct internal exceptions. The runner maps those to `TOOL_TIMEOUT` and `TOOL_EXECUTION_FAILED` and never retries.

- [ ] **Step 4: Implement the same validation/budget state machine as TypeScript**

Keep event names, event payload keys, counter semantics, and ordering identical to Task 3. The only parity-ignored event fields remain the existing volatile envelope fields.

Scripted model errors emit `model.failed` and terminate as `INVALID_MODEL_DECISION`.

- [ ] **Step 5: Add mirrored failure/boundary tests**

Cover all six canonical failures plus:

- valid final on exact step limit;
- valid final on exact token limit;
- invalid model envelope does not add unvalidated usage;
- direct-mode timeout uses the same executor and has zero model events;
- step/token rejected decisions do not add an extra `tool.requested`.

- [ ] **Step 6: Prove Python import and all canonical runs are network-denied**

Patch `socket.create_connection` and `socket.socket` before importing `boundrelay_m1.runner`, probe that the guard fires, then run all eight canonical cases.

Also use a fresh-interpreter import probe equivalent to M0 so import-time networking cannot be hidden by module cache.

- [ ] **Step 7: Implement CLI and run Python checks**

`cli.py` uses argparse choices `direct|agent`; `main()` passes the parsed `mode`, `case_id`, and `trace_path` into `asyncio.run(run_scenario_case(...))`, emits one compact JSON stdout line, writes diagnostics to stderr, and returns exit code `2` on failure.

Run:

```bash
PYTHONPATH=lessons/01-bounded-tool-loop/python/src python -m unittest discover -s lessons/01-bounded-tool-loop/python/tests -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add lessons/01-bounded-tool-loop/python
git commit -m "feat(m1): implement Python bounded tool loop"
```

---

### Task 6: Add cross-language M1 parity and revision-bound certification

**Files:**
- Create: `tools/parity/verify_m1.py`
- Create: `tools/parity/test_m1_verification_safety.py`
- Create: `scripts/verify_m1.py`
- Reuse without modifying unless a failing M1 test proves necessary: `tools/parity/normalize.py`

**Interfaces:**
- Consumes: both CLIs, Task 1 scenario/result/event contracts, existing strict JSONL reader/normalizer.
- Produces:
  - local authority `python scripts/verify_m1.py`;
  - `.boundrelay/m1/traces/*.jsonl`;
  - `.boundrelay/m1/verification-evidence.json` tied to the exact candidate revision.

- [ ] **Step 1: Write failing verifier-safety tests**

Create tests for:

```python
with self.assertRaisesRegex(AssertionError, "wrong case_id"):
    verifier._assert_result_context(
        {"case_id": "other", "mode": "agent", "trace_path": "/tmp/a.jsonl"},
        expected_case_id="agent-delayed-shipment",
        expected_mode="agent",
        expected_trace_path="/tmp/a.jsonl",
        label="sample",
    )

with self.assertRaisesRegex(AssertionError, "wrong run_id"):
    verifier._assert_trace_integrity(
        [
            {"run_id": "run-1", "sequence": 1, "type": "run.created"},
            {"run_id": "run-2", "sequence": 2, "type": "run.failed"},
        ],
        expected_run_id="run-1",
        label="sample",
        validate_schema=False,
    )

verifier._assert_case_behavior(
    case={"id": "agent-unknown-tool", "expected_failure_code": "UNKNOWN_TOOL",
          "expected_tool_invocations": 0},
    result={"status": "FAILED", "failure_code": "UNKNOWN_TOOL",
            "tool_invocations": 0},
    events=[{"type": "model.completed"}, {"type": "run.failed"}],
    label="unknown-tool",
)

with self.assertRaisesRegex(AssertionError, "tool.requested"):
    verifier._assert_case_behavior(
        case={"id": "agent-step-budget", "expected_failure_code": "STEP_BUDGET_EXCEEDED",
              "expected_tool_invocations": 1},
        result={"status": "FAILED", "failure_code": "STEP_BUDGET_EXCEEDED",
                "tool_invocations": 1},
        events=[
            {"type": "tool.requested", "data": {"tool": "lookup_order"}},
            {"type": "tool.completed", "data": {"tool": "lookup_order"}},
            {"type": "tool.requested", "data": {"tool": "lookup_shipment"}},
            {"type": "run.failed"},
        ],
        label="step-budget",
    )
```

Add separate mocked provenance tests, following the M0 safety-test style, that assert `assert_clean_worktree()` is called before and immediately before evidence publication, a changed second `HEAD` raises `RuntimeError("revision changed")`, and `clear_previous_evidence()` runs before the first gate command. Timeout/execution-failure fixtures must assert exactly one `tool.requested` and one `tool.failed`.

Also pin `scenario_id == "order-investigation"` in evidence.

- [ ] **Step 2: Implement CLI execution and contract validation**

`tools/parity/verify_m1.py` executes both runtimes for each of the eight case/mode pairs with unique requested trace paths, requires exactly one nonblank JSON stdout line, validates the M1 result schema, parses each trace with existing strict `read_jsonl()`, and validates every event with the shared event schema.

- [ ] **Step 3: Implement semantic invariant checks**

For each case, assert fixture-defined:

- status, answer/failure code;
- `model_steps`, `tokens_used`, `tool_invocations`;
- tool request order/count;
- no model events in direct mode;
- no tool request after unknown/invalid/step/token rejection;
- one tool failure event for timeout/execution failure;
- one stable run ID, contiguous sequences, one terminal event;
- terminal payload counters/failure agree with result.

For successful agent mode, assert normalized tool path exactly `lookup_order -> lookup_shipment -> final`.

- [ ] **Step 4: Compare normalized TypeScript/Python behavior**

Reuse `normalize_result()` and `normalized_trace()`. For every canonical case:

```python
self.assertEqual(normalize_result(ts_result), normalize_result(py_result))
self.assertEqual(normalized_trace(ts_trace), normalized_trace(py_trace))
```

Do not add language-specific exceptions to the normalizer for M1.

- [ ] **Step 5: Implement evidence provenance**

Before scenario execution:

1. require clean worktree;
2. capture `HEAD`;
3. capture Node/npm/Python versions.

Immediately before writing PASSED evidence:

1. require clean worktree again;
2. read `HEAD` again;
3. reject if revision changed.

Evidence records exact revision, command, scenario ID, runtime versions, eight case records, result status/counters, and both trace paths.

- [ ] **Step 6: Implement the top-level gate**

`scripts/verify_m1.py` must clear `.boundrelay/m1/` before the first check, then run in this order:

```text
python scripts/verify_m0.py
python -m unittest tools.contracts.test_m1_contracts -v
npm --prefix lessons/01-bounded-tool-loop/typescript run typecheck
npm --prefix lessons/01-bounded-tool-loop/typescript test
python -m unittest discover -s lessons/01-bounded-tool-loop/python/tests -v
python -m unittest tools.parity.test_normalize tools.parity.test_trace_contract tools.parity.test_m1_verification_safety -v
python -m tools.parity.verify_m1
```

Use `PYTHONPATH=lessons/01-bounded-tool-loop/python/src` for M1 Python tests/verifier commands. M0 remains its own authority command even though M1 invokes it as a regression gate.

- [ ] **Step 7: Run focused verification tests and commit**

Before the revision-bound full gate, run the dirty-worktree-safe unit subsets:

```bash
python -m unittest tools.contracts.test_m1_contracts tools.parity.test_m1_verification_safety -v
npm --prefix lessons/01-bounded-tool-loop/typescript run typecheck
npm --prefix lessons/01-bounded-tool-loop/typescript test
PYTHONPATH=lessons/01-bounded-tool-loop/python/src python -m unittest discover -s lessons/01-bounded-tool-loop/python/tests -v
```

Then commit:

```bash
git add tools/parity scripts/verify_m1.py
git commit -m "test(m1): add parity and revision-bound verification"
```

---

### Task 7: Add lesson documentation, CI, and final exact-revision evidence

**Files:**
- Create: `lessons/01-bounded-tool-loop/README.md`
- Create: `.github/workflows/m1.yml`
- Modify: `README.md`
- Modify: `README.tr.md`

**Interfaces:**
- Consumes: completed Tasks 1–6 and accepted M1 spec.
- Produces: documented Lesson 01, one-command local setup/verification, GitHub Actions exact-head evidence, and repository status reflecting completed M1.

- [ ] **Step 1: Write Lesson 01 documentation**

Use the foundation lesson contract headings exactly:

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

The documentation must explicitly contrast:

```text
Show order ORD-1001 status.       -> direct lookup_order call
Why is order ORD-1001 delayed?    -> bounded model/tool/observation loop
```

It must explain the six canonical failures, hard step/token boundaries, read-only restriction, and why retries/side effects are deferred.

- [ ] **Step 2: Add the M1 GitHub Actions workflow**

Mirror M0's exact-head checkout and action majors:

- `actions/checkout@v7`;
- `actions/setup-node@v7`;
- `actions/setup-python@v7`;
- `actions/upload-artifact@v7`;
- Node/Python versions from root marker files;
- npm cache includes both Lesson 00 and Lesson 01 lockfiles;
- install editable Python packages for both lessons;
- run `npm ci` for both lessons;
- execute only `python scripts/verify_m1.py` as the M1 authority;
- upload `.boundrelay/m1/` as `m1-verification-<exact-head-sha>`;
- `if-no-files-found: error`, hidden files included, retention 14 days.

Set workflow timeout to 15 minutes.

- [ ] **Step 3: Update root English/Turkish status only after implementation exists**

Change repository phase/status from M0-only completion to M1 completion while preserving the M0 verification instructions. Add the M1 setup additions:

```bash
python -m pip install -e lessons/01-bounded-tool-loop/python
npm ci --prefix lessons/01-bounded-tool-loop/typescript
python scripts/verify_m1.py
```

Do not claim real-provider support, Go parity, persistence, retry, MCP, or framework mappings.

- [ ] **Step 4: Commit documentation and CI**

```bash
git add lessons/01-bounded-tool-loop/README.md .github/workflows/m1.yml README.md README.tr.md
git commit -m "docs(m1): add lesson and verification workflow"
```

- [ ] **Step 5: Run the exact-revision certification gate**

The worktree must now be clean.

Run:

```bash
python scripts/verify_m1.py
```

Expected:

- M0 authority passes;
- M1 contract tests pass;
- TypeScript typecheck/tests pass;
- Python tests pass;
- parity/safety/strict-trace tests pass;
- all eight TypeScript/Python canonical runs match;
- `.boundrelay/m1/verification-evidence.json` reports `PASSED`;
- evidence revision equals `git rev-parse HEAD`.

- [ ] **Step 6: Inspect evidence before PR review**

Confirm:

```bash
git status --short
git rev-parse HEAD
python -m json.tool .boundrelay/m1/verification-evidence.json
```

Expected: clean worktree; evidence revision equals HEAD; eight canonical case records exist.

Do not add generated `.boundrelay/` evidence to Git.

---

## Dependency Order

```text
Task 1  canonical contracts/fixtures
   ↓
Task 2  TypeScript domain/tool foundations
   ↓
Task 3  TypeScript runtime
   ↓
Task 4  Python domain/tool foundations
   ↓
Task 5  Python runtime
   ↓
Task 6  cross-language parity + certification
   ↓
Task 7  docs + CI + exact-revision evidence
```

Tasks 2–3 and 4–5 are conceptually parallel, but implementation should keep the sequence above so the Python track can compare observable choices against the already-reviewed TypeScript track without making TypeScript canonical. Any discovered contract mismatch must be fixed in Task 1 assets/contracts first, then both languages updated.

## Scope Stop Conditions

Stop implementation and return to the D-012 decision gate if any task appears to require:

- a third tool;
- any mutating/side-effecting tool;
- retry/backoff semantics;
- persistence/checkpoints;
- approval/idempotency;
- real model provider integration;
- Go;
- MCP or framework adapters;
- a reusable shared runtime extracted from Lesson 00/01;
- a ninth canonical parity case;
- a new failure code outside the accepted six plus `INVALID_MODEL_DECISION`;
- changing the accepted step/token accounting semantics.

