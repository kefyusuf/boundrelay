# M0 Behavioral Parity Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one offline support-triage lesson whose TypeScript and Python implementations produce schema-valid, behaviorally equivalent results and JSONL traces for deterministic routing, bounded model routing, and an invalid-route failure.

**Architecture:** Canonical scenarios, fake-model responses, schemas, and invariants live outside either language implementation. TypeScript and Python implement the same observable contract idiomatically. A Python verifier executes both CLIs, validates artifacts, normalizes volatile fields, compares behavior, and emits revision-bound evidence.

**Tech Stack:** Node.js 24 LTS, TypeScript 7.0.2, `tsx` 4.23.13, Vitest 4.1.7, Ajv 8.20.0, `yaml` 2.9.0, Python 3.14, PyYAML 6.0.3, jsonschema 4.26.0, Python `unittest`, JSON Schema Draft 2020-12, GitHub Actions v7.

**Spec:** `docs/design/2026-09-02-foundation-design.md`

## Global Constraints

- M0 contains one support-triage scenario and only the routes `billing`, `technical`, and `general`.
- TypeScript and Python are the only M0 implementations; neither language is canonical.
- Every command must run without network access during scenario execution and without an API key.
- The deterministic router is the preferred baseline; the model path exists to teach validation of untrusted decisions.
- Unknown model routes fail closed, emit `route.rejected`, return `FAILED`, and never invoke a specialist.
- Every run emits monotonically increasing sequence numbers and exactly one terminal run event.
- Parity ignores timestamps, generated IDs, trace paths, and language identifiers but preserves event types, step names, routes, statuses, failure codes, and specialist invocation behavior.
- Verification evidence must record the current Git revision, runtime versions, command, cases, result, and trace locations.
- No real provider, Go code, persistence, MCP, framework adapter, queue, web UI, plugin system, or reusable runtime package is included.
- JSON Schema uses Draft 2020-12. Node floor is `24`; Python floor is `3.14`.

## Planned File Map

```text
boundrelay/
├── .editorconfig
├── .gitignore
├── .nvmrc
├── .python-version
├── requirements-dev.txt
├── contracts/
│   ├── events/run-event.schema.json
│   ├── results/run-result.schema.json
│   └── routing/route-decision.schema.json
├── fixtures/
│   ├── fake-model/support-triage.yaml
│   └── scenarios/support-triage.yaml
├── lessons/00-workflow-or-agent/
│   ├── README.md
│   ├── invariants.yaml
│   ├── typescript/
│   │   ├── package.json
│   │   ├── package-lock.json
│   │   ├── tsconfig.json
│   │   ├── src/{cli,paths,types,schemas,scenario,trace,deterministic-router,bounded-router,fake-decision-provider,specialists,runner}.ts
│   │   └── test/{schemas,trace,routing,runner}.test.ts
│   └── python/
│       ├── pyproject.toml
│       ├── src/boundrelay_m0/{__init__,__main__,cli,paths,types,schemas,scenario,trace,deterministic_router,bounded_router,fake_decision_provider,specialists,runner}.py
│       └── tests/{test_schemas,test_trace,test_routing,test_runner}.py
├── tools/
│   ├── __init__.py
│   ├── contracts/{__init__.py,test_contracts.py}
│   └── parity/{__init__.py,normalize.py,test_normalize.py,verify_m0.py}
├── scripts/verify_m0.py
└── .github/workflows/m0.yml
```

---

### Task 1: Add toolchain markers and canonical M0 assets

**Files:**
- Create: `.editorconfig`
- Create: `.gitignore`
- Create: `.nvmrc`
- Create: `.python-version`
- Create: `requirements-dev.txt`
- Create: `fixtures/scenarios/support-triage.yaml`
- Create: `fixtures/fake-model/support-triage.yaml`
- Create: `lessons/00-workflow-or-agent/invariants.yaml`
- Create: `tools/__init__.py`
- Create: `tools/contracts/__init__.py`
- Create: `tools/contracts/test_contracts.py`

**Interfaces:**
- Consumes: accepted routes and M0 invariants from the spec.
- Produces: stable case IDs and canonical assets used by every later task.

- [ ] **Step 1: Write the failing canonical-asset test**

Create `tools/contracts/test_contracts.py`:

```python
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCENARIO = ROOT / "fixtures/scenarios/support-triage.yaml"
FAKE = ROOT / "fixtures/fake-model/support-triage.yaml"
INVARIANTS = ROOT / "lessons/00-workflow-or-agent/invariants.yaml"


class CanonicalAssetTests(unittest.TestCase):
    def test_assets_define_matching_cases_and_routes(self) -> None:
        scenario = yaml.safe_load(SCENARIO.read_text(encoding="utf-8"))
        fake = yaml.safe_load(FAKE.read_text(encoding="utf-8"))
        invariants = yaml.safe_load(INVARIANTS.read_text(encoding="utf-8"))

        self.assertEqual(scenario["schema_version"], "1.0")
        self.assertEqual(scenario["scenario_id"], "support-triage")
        self.assertEqual(scenario["routes"], ["billing", "technical", "general"])
        case_ids = {case["id"] for case in scenario["cases"]}
        self.assertEqual(case_ids, set(fake["responses"]))
        self.assertEqual(len(invariants["invariants"]), 10)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and confirm the expected failure**

```bash
python -m unittest tools.contracts.test_contracts -v
```

Expected: `FileNotFoundError` for the first missing canonical asset.

- [ ] **Step 3: Add exact toolchain files**

Create `.nvmrc` with `24`, `.python-version` with `3.14`, and `requirements-dev.txt`:

```text
PyYAML==6.0.3
jsonschema[format]==4.26.0
```

Create `.gitignore`:

```gitignore
.venv/
__pycache__/
*.py[cod]
node_modules/
.boundrelay/
.DS_Store
```

Create `.editorconfig`:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
indent_style = space
indent_size = 2

[*.py]
indent_size = 4
```

- [ ] **Step 4: Add the canonical scenario**

Create `fixtures/scenarios/support-triage.yaml`:

```yaml
schema_version: "1.0"
scenario_id: support-triage
routes: [billing, technical, general]
cases:
  - id: billing-duplicate-charge
    request: I was charged twice for the same invoice.
    expected_route: billing
  - id: technical-login-error
    request: I cannot log in because the app shows an error.
    expected_route: technical
  - id: general-opening-hours
    request: What are your support opening hours?
    expected_route: general
  - id: invalid-model-route
    request: Route this request through the scripted invalid decision.
    expected_failure_code: INVALID_ROUTE_DECISION
```

Create `fixtures/fake-model/support-triage.yaml`:

```yaml
schema_version: "1.0"
scenario_id: support-triage
responses:
  billing-duplicate-charge:
    return: {route: billing, confidence: 0.98}
  technical-login-error:
    return: {route: technical, confidence: 0.97}
  general-opening-hours:
    return: {route: general, confidence: 0.94}
  invalid-model-route:
    return: {route: unknown-specialist, confidence: 0.99}
```

Create `lessons/00-workflow-or-agent/invariants.yaml` with IDs `M0-I01` through `M0-I10` covering the ten M0 invariants in section 11.4 of the spec.

- [ ] **Step 5: Run the contract test**

```bash
python -m unittest tools.contracts.test_contracts -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add .editorconfig .gitignore .nvmrc .python-version requirements-dev.txt fixtures lessons/00-workflow-or-agent/invariants.yaml tools
git commit -m "test(contracts): add canonical M0 assets"
```

---

### Task 2: Define shared JSON Schemas and validate contracts

**Files:**
- Create: `contracts/routing/route-decision.schema.json`
- Create: `contracts/events/run-event.schema.json`
- Create: `contracts/results/run-result.schema.json`
- Modify: `tools/contracts/test_contracts.py`

**Interfaces:**
- Consumes: canonical routes and event names.
- Produces: runtime validation boundaries for both language tracks and parity tooling.

- [ ] **Step 1: Add failing schema tests**

Append to `CanonicalAssetTests`:

```python
import json
from jsonschema import Draft202012Validator

    def test_schemas_accept_valid_and_reject_invalid_boundaries(self) -> None:
        route_schema = json.loads((ROOT / "contracts/routing/route-decision.schema.json").read_text())
        result_schema = json.loads((ROOT / "contracts/results/run-result.schema.json").read_text())
        route_validator = Draft202012Validator(route_schema)
        result_validator = Draft202012Validator(result_schema)

        self.assertFalse(list(route_validator.iter_errors({"route": "billing", "confidence": 0.9})))
        self.assertTrue(list(route_validator.iter_errors({"route": "unknown", "confidence": 0.9})))
        self.assertFalse(list(result_validator.iter_errors({
            "schema_version": "1.0", "run_id": "run-1", "scenario_id": "support-triage",
            "case_id": "billing-duplicate-charge", "mode": "deterministic", "status": "SUCCEEDED",
            "selected_route": "billing", "specialist_invoked": True, "failure_code": None,
            "trace_path": ".boundrelay/m0/trace.jsonl",
        })))
```

- [ ] **Step 2: Run and confirm missing-schema failure**

```bash
python -m unittest tools.contracts.test_contracts -v
```

Expected: `FileNotFoundError` under `contracts/`.

- [ ] **Step 3: Implement the schemas**

`route-decision.schema.json` must require exactly `route` and `confidence`; route is the three-value enum and confidence is a number from `0` through `1`.

`run-event.schema.json` must require:

```json
{
  "schema_version": "1.0",
  "event_id": "evt-1",
  "run_id": "run-1",
  "sequence": 1,
  "type": "run.created",
  "timestamp": "2026-09-02T00:00:00Z",
  "source": "typescript",
  "data": {}
}
```

Allowed M0 event types are `run.created`, `run.started`, `run.completed`, `run.failed`, `step.started`, `step.completed`, `step.failed`, `model.requested`, `model.completed`, `model.failed`, `route.selected`, and `route.rejected`. `source` is `typescript` or `python`; `sequence` is an integer of at least `1`; `timestamp` uses `date-time`; additional properties are rejected.

`run-result.schema.json` must require the fields in the valid test above, allow modes `deterministic|model`, statuses `SUCCEEDED|FAILED`, routes plus `null`, and failure code `INVALID_ROUTE_DECISION|null`. Use conditional schema rules so success requires a route, `specialist_invoked: true`, and `failure_code: null`; failure requires `selected_route: null`, `specialist_invoked: false`, and a non-null failure code.

- [ ] **Step 4: Validate all canonical documents and schema declarations**

Add a test that calls `Draft202012Validator.check_schema()` for all three schemas and verifies every scenario case has exactly one of `expected_route` or `expected_failure_code`.

- [ ] **Step 5: Run tests and commit**

```bash
python -m unittest tools.contracts.test_contracts -v
git add contracts tools/contracts/test_contracts.py
git commit -m "feat(contracts): define M0 schemas"
```

---

### Task 3: Build the TypeScript implementation with TDD

**Files:**
- Create: `lessons/00-workflow-or-agent/typescript/package.json`
- Create: `lessons/00-workflow-or-agent/typescript/package-lock.json`
- Create: `lessons/00-workflow-or-agent/typescript/tsconfig.json`
- Create: `lessons/00-workflow-or-agent/typescript/src/*.ts`
- Create: `lessons/00-workflow-or-agent/typescript/test/*.test.ts`

**Interfaces:**
- Consumes: shared scenario, fake responses, and schemas.
- Produces: `runScenarioCase(options): Promise<RunResult>` and a CLI that prints one JSON result and writes one JSONL trace.

- [ ] **Step 1: Write routing and runner tests before implementation**

`routing.test.ts` must assert:

```typescript
expect(classifyDeterministically("I was charged twice")).toEqual({route: "billing", confidence: 1});
expect(classifyDeterministically("The app shows an error")).toEqual({route: "technical", confidence: 1});
expect(classifyDeterministically("What are your hours?")).toEqual({route: "general", confidence: 1});
expect(routeDecision({route: "unknown-specialist", confidence: 0.99})).toEqual({
  ok: false,
  failureCode: "INVALID_ROUTE_DECISION",
  rejectedRoute: "unknown-specialist",
});
```

`runner.test.ts` must run a valid model case and the invalid case using a fixed clock and fixed ID factory. Assert one terminal event, monotonic sequences, `route.rejected` on failure, and no `specialist.*` step on failure.

- [ ] **Step 2: Add package configuration and confirm tests fail**

Create `package.json`:

```json
{
  "name": "@boundrelay/lesson-00-typescript",
  "version": "0.0.0",
  "private": true,
  "type": "module",
  "engines": {"node": ">=24"},
  "scripts": {"typecheck": "tsc --noEmit", "test": "vitest run", "run": "tsx src/cli.ts"},
  "dependencies": {"ajv": "8.20.0", "ajv-formats": "3.0.1", "yaml": "2.9.0"},
  "devDependencies": {"@types/node": "^24.0.0", "tsx": "4.23.13", "typescript": "7.0.2", "vitest": "4.1.7"}
}
```

Create `tsconfig.json` with `target: ES2024`, `module/moduleResolution: NodeNext`, `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `verbatimModuleSyntax`, `noEmit`, and Node/Vitest types.

```bash
npm install --prefix lessons/00-workflow-or-agent/typescript
npm --prefix lessons/00-workflow-or-agent/typescript test
```

Expected: FAIL because source modules do not exist.

- [ ] **Step 3: Implement exact TypeScript domain boundaries**

In `types.ts`, define:

```typescript
export const ROUTES = ["billing", "technical", "general"] as const;
export type Route = typeof ROUTES[number];
export type RunMode = "deterministic" | "model";
export type RunStatus = "SUCCEEDED" | "FAILED";
export interface RouteDecision { route: Route; confidence: number }
export interface DecisionProvider { classify(input: {caseId: string; request: string}): Promise<unknown> }
export interface RunResult {
  schema_version: "1.0"; run_id: string; scenario_id: "support-triage"; case_id: string;
  mode: RunMode; status: RunStatus; selected_route: Route | null; specialist_invoked: boolean;
  failure_code: "INVALID_ROUTE_DECISION" | null; trace_path: string;
}
```

`paths.ts` resolves the repository root from `import.meta.url`. `schemas.ts` loads the three shared schemas with Ajv 2020 and exposes `validateRouteDecision`, `validateRunEvent`, and `validateRunResult` as discriminated validation results.

- [ ] **Step 4: Implement deterministic and bounded routing**

```typescript
export function classifyDeterministically(request: string): RouteDecision {
  const value = request.toLowerCase();
  if (["charged", "charge", "invoice", "payment", "refund", "billed"].some((x) => value.includes(x)))
    return {route: "billing", confidence: 1};
  if (["error", "crash", "cannot log in", "can't log in", "bug", "broken"].some((x) => value.includes(x)))
    return {route: "technical", confidence: 1};
  return {route: "general", confidence: 1};
}

export function routeDecision(raw: unknown):
  | {ok: true; decision: RouteDecision}
  | {ok: false; failureCode: "INVALID_ROUTE_DECISION"; rejectedRoute: string | null} {
  const validated = validateRouteDecision(raw);
  if (validated.ok) return {ok: true, decision: validated.value};
  const rejectedRoute = typeof raw === "object" && raw !== null && "route" in raw && typeof raw.route === "string"
    ? raw.route : null;
  return {ok: false, failureCode: "INVALID_ROUTE_DECISION", rejectedRoute};
}
```

- [ ] **Step 5: Implement trace, fake provider, specialist recorder, runner, and CLI**

`MemoryEventSink.emit()` increments sequence before validating and storing the event. `writeJsonl()` creates parent directories and writes one compact JSON object per line. Optional `clock` and `idFactory` properties explicitly permit `undefined` under `exactOptionalPropertyTypes`.

`ScriptedDecisionProvider` reads the YAML response map and throws a configuration error when a case ID is missing. `RecordingSpecialistDispatcher` stores immutable `{route, request}` invocations.

`runScenarioCase()` must emit this success order:

```text
run.created → run.started → step.started(classify) → [model.requested → model.completed]
→ route.selected → step.completed(classify) → step.started(specialist.<route>)
→ step.completed(specialist.<route>) → run.completed
```

The invalid model case must emit:

```text
run.created → run.started → step.started(classify) → model.requested → model.completed
→ route.rejected → step.failed(classify) → run.failed
```

The CLI contract is:

```bash
npm --prefix lessons/00-workflow-or-agent/typescript run run -- \
  --mode model --case billing-duplicate-charge --trace .boundrelay/manual/ts.jsonl
```

It prints only the final JSON result to stdout; progress or diagnostics go to stderr.

- [ ] **Step 6: Run TypeScript verification and commit**

```bash
npm --prefix lessons/00-workflow-or-agent/typescript run typecheck
npm --prefix lessons/00-workflow-or-agent/typescript test
git add lessons/00-workflow-or-agent/typescript
git commit -m "feat(ts): implement M0 routing and trace"
```

---

### Task 4: Build the Python implementation with TDD

**Files:**
- Create: `lessons/00-workflow-or-agent/python/pyproject.toml`
- Create: `lessons/00-workflow-or-agent/python/src/boundrelay_m0/*.py`
- Create: `lessons/00-workflow-or-agent/python/tests/*.py`

**Interfaces:**
- Consumes: the same shared assets as TypeScript.
- Produces: `run_scenario_case(...) -> RunResult` and `python -m boundrelay_m0` with the same CLI/result contract.

- [ ] **Step 1: Write failing Python tests**

Use `unittest`. Tests must assert the same deterministic routes, invalid-route rejection, event ordering, terminal-event count, monotonic sequences, schema-valid result, and absence of specialist events on rejection as the TypeScript tests.

```python
self.assertEqual(classify_deterministically("I was charged twice"), RouteDecision("billing", 1.0))
self.assertEqual(route_decision({"route": "unknown-specialist", "confidence": 0.99}),
                 RejectedRoute("INVALID_ROUTE_DECISION", "unknown-specialist"))
```

- [ ] **Step 2: Add package configuration and confirm tests fail**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=80"]
build-backend = "setuptools.build_meta"

[project]
name = "boundrelay-m0"
version = "0.0.0"
requires-python = ">=3.14"
dependencies = ["PyYAML==6.0.3", "jsonschema[format]==4.26.0"]

[tool.setuptools.packages.find]
where = ["src"]
```

```bash
python -m pip install -e lessons/00-workflow-or-agent/python
python -m unittest discover -s lessons/00-workflow-or-agent/python/tests -v
```

Expected: FAIL because `boundrelay_m0` modules do not exist.

- [ ] **Step 3: Implement Python domain and schema adapters**

Use frozen dataclasses and `Literal` aliases:

```python
Route = Literal["billing", "technical", "general"]
RunMode = Literal["deterministic", "model"]

@dataclass(frozen=True)
class RouteDecision:
    route: Route
    confidence: float

@dataclass(frozen=True)
class RunResult:
    schema_version: Literal["1.0"]
    run_id: str
    scenario_id: Literal["support-triage"]
    case_id: str
    mode: RunMode
    status: Literal["SUCCEEDED", "FAILED"]
    selected_route: Route | None
    specialist_invoked: bool
    failure_code: Literal["INVALID_ROUTE_DECISION"] | None
    trace_path: str
```

`schemas.py` loads the same shared JSON files with `Draft202012Validator`; valid route payloads become `RouteDecision`, invalid values become a `ValidationFailure` containing stable error strings.

- [ ] **Step 4: Implement routing and execution components**

`classify_deterministically()` uses the exact keyword sets from TypeScript. `route_decision()` validates before constructing a `RouteDecision`; it returns `RejectedRoute("INVALID_ROUTE_DECISION", rejected_route)` on failure.

`MemoryEventSink` uses injected `clock` and `id_factory`, validates every event, stores immutable snapshots, and writes compact JSONL. `ScriptedDecisionProvider` deep-copies fixture values. `RecordingSpecialistDispatcher` exposes a tuple of invocations.

`run_scenario_case()` must emit the same semantic order and result fields as TypeScript. The module CLI accepts `--mode`, `--case`, and `--trace`, writes a JSONL trace, and prints one compact JSON result.

- [ ] **Step 5: Prove offline behavior and run tests**

Patch `socket.create_connection` in runner tests to raise if called. Execute:

```bash
python -m unittest discover -s lessons/00-workflow-or-agent/python/tests -v
PYTHONPATH=lessons/00-workflow-or-agent/python/src \
python -m boundrelay_m0 --mode model --case invalid-model-route --trace .boundrelay/manual/py-invalid.jsonl
```

Expected: tests pass; CLI returns `FAILED/INVALID_ROUTE_DECISION`; no network call occurs.

- [ ] **Step 6: Commit**

```bash
git add lessons/00-workflow-or-agent/python
git commit -m "feat(py): implement M0 routing and trace"
```

---

### Task 5: Add normalization and cross-language parity verification

**Files:**
- Create: `tools/parity/__init__.py`
- Create: `tools/parity/normalize.py`
- Create: `tools/parity/test_normalize.py`
- Create: `tools/parity/verify_m0.py`

**Interfaces:**
- Consumes: both CLIs, shared schemas, scenario cases, and generated traces.
- Produces: a single pass/fail authority and `.boundrelay/m0/verification-evidence.json`.

- [ ] **Step 1: Write failing normalizer tests**

```python
from tools.parity.normalize import normalize_event, normalize_result

class NormalizeTests(unittest.TestCase):
    def test_event_removes_only_volatile_fields(self) -> None:
        event = {"schema_version": "1.0", "event_id": "evt-ts", "run_id": "run-ts",
                 "sequence": 1, "timestamp": "2026-09-02T00:00:00Z", "source": "typescript",
                 "type": "route.selected", "data": {"route": "billing"}}
        self.assertEqual(normalize_event(event),
                         {"schema_version": "1.0", "sequence": 1, "type": "route.selected",
                          "data": {"route": "billing"}})

    def test_result_removes_run_and_path_but_keeps_behavior(self) -> None:
        result = {"schema_version": "1.0", "run_id": "run-ts", "scenario_id": "support-triage",
                  "case_id": "x", "mode": "model", "status": "FAILED", "selected_route": None,
                  "specialist_invoked": False, "failure_code": "INVALID_ROUTE_DECISION",
                  "trace_path": "volatile"}
        normalized = normalize_result(result)
        self.assertNotIn("run_id", normalized)
        self.assertNotIn("trace_path", normalized)
        self.assertEqual(normalized["failure_code"], "INVALID_ROUTE_DECISION")
```

- [ ] **Step 2: Run and confirm failure**

```bash
python -m unittest tools.parity.test_normalize -v
```

Expected: import failure because `normalize.py` does not exist.

- [ ] **Step 3: Implement normalization**

```python
VOLATILE_EVENT_FIELDS = {"event_id", "run_id", "timestamp", "source"}
VOLATILE_RESULT_FIELDS = {"run_id", "trace_path"}


def normalize_event(event: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in event.items() if key not in VOLATILE_EVENT_FIELDS}


def normalize_result(result: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in result.items() if key not in VOLATILE_RESULT_FIELDS}
```

`read_jsonl(path)` rejects empty files and non-object lines. `normalized_trace(path)` maps `normalize_event` over the ordered events.

- [ ] **Step 4: Implement the parity verifier**

`python -m tools.parity.verify_m0` must:

1. load the scenario and schemas;
2. execute deterministic and model modes for each valid case plus model mode for `invalid-model-route`—seven combinations total;
3. invoke TypeScript through `npm --prefix ... run run -- ...` and Python through `python -m boundrelay_m0 ...` with `PYTHONPATH` set;
4. parse the last stdout line as the result;
5. validate every result and event;
6. assert sequences equal `1..N` and exactly one terminal event exists;
7. assert route success or fail-closed behavior;
8. compare normalized TypeScript and Python results and traces;
9. write evidence containing revision, UTC generation time, runtime versions, verification command, status, and per-case trace paths.

Use this exact evidence command field:

```json
{"verification_command": "python -m tools.parity.verify_m0"}
```

- [ ] **Step 5: Run parity verification and commit**

```bash
python -m unittest tools.parity.test_normalize -v
python -m tools.parity.verify_m0
git add tools/parity
git commit -m "test(parity): verify TypeScript and Python M0 behavior"
```

Expected: seven combinations pass and `.boundrelay/m0/verification-evidence.json` records the current revision.

---

### Task 6: Add one-command verification and lesson documentation

**Files:**
- Create: `scripts/verify_m0.py`
- Create: `lessons/00-workflow-or-agent/README.md`
- Modify: `README.md`
- Modify: `README.tr.md`
- Modify: `.ai/delivery/current-scope.md`

**Interfaces:**
- Consumes: all test and parity commands.
- Produces: the sole documented local M0 gate and the complete Lesson 00 teaching narrative.

- [ ] **Step 1: Implement the verification orchestrator**

```python
from pathlib import Path
import os, subprocess, sys

ROOT = Path(__file__).resolve().parents[1]
TS = ROOT / "lessons/00-workflow-or-agent/typescript"
PY_SRC = ROOT / "lessons/00-workflow-or-agent/python/src"
PY_TESTS = ROOT / "lessons/00-workflow-or-agent/python/tests"


def run(command: list[str], env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def main() -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PY_SRC)
    run([sys.executable, "-m", "unittest", "tools.contracts.test_contracts", "-v"])
    run(["npm", "--prefix", str(TS), "run", "typecheck"])
    run(["npm", "--prefix", str(TS), "test"])
    run([sys.executable, "-m", "unittest", "discover", "-s", str(PY_TESTS), "-v"], env)
    run([sys.executable, "-m", "unittest", "tools.parity.test_normalize", "-v"])
    run([sys.executable, "-m", "tools.parity.verify_m0"], env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Write Lesson 00 documentation**

The lesson README must contain these top-level sections in order: Problem, Success criteria, Deterministic baseline, Reason to introduce model judgment, Naive implementation, Failure injection, Corrected implementation, Verification evidence, Trade-offs, When not to use this pattern, Exercises.

Include exact TypeScript and Python commands for one deterministic success and `invalid-model-route`. The naive section must show the unsafe cast/index access. The correction must explain schema validation before dispatch. The evidence section must point to `.boundrelay/m0/verification-evidence.json` and per-language JSONL traces. The trade-off table compares cost, latency, auditability, flexibility, and failure surface.

- [ ] **Step 3: Update root docs and active scope**

Document this setup path in English and Turkish:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install -e lessons/00-workflow-or-agent/python
npm ci --prefix lessons/00-workflow-or-agent/typescript
python scripts/verify_m0.py
```

Keep project status as “M0 in implementation” until current-revision local and CI evidence pass. Do not mark M0 complete in this task.

- [ ] **Step 4: Run the documented gate and commit**

```bash
python scripts/verify_m0.py
git add scripts lessons/00-workflow-or-agent/README.md README.md README.tr.md .ai/delivery/current-scope.md
git commit -m "docs: add executable M0 learning path"
```

---

### Task 7: Add GitHub Actions verification and close M0 only with evidence

**Files:**
- Create: `.github/workflows/m0.yml`
- Modify: `tools/contracts/test_contracts.py`
- Modify after green CI: `.ai/delivery/current-scope.md`

**Interfaces:**
- Consumes: `python scripts/verify_m0.py`.
- Produces: current-commit CI status and retained M0 evidence artifacts.

- [ ] **Step 1: Add the workflow**

```yaml
name: M0 Verification

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  verify:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with:
          node-version-file: .nvmrc
          cache: npm
          cache-dependency-path: lessons/00-workflow-or-agent/typescript/package-lock.json
      - uses: actions/setup-python@v7
        with:
          python-version-file: .python-version
          cache: pip
          cache-dependency-path: requirements-dev.txt
      - run: |
          python -m pip install --upgrade pip
          python -m pip install -r requirements-dev.txt
          python -m pip install -e lessons/00-workflow-or-agent/python
      - run: npm ci --prefix lessons/00-workflow-or-agent/typescript
      - run: python scripts/verify_m0.py
      - if: always()
        uses: actions/upload-artifact@v7
        with:
          name: m0-verification-${{ github.sha }}
          path: .boundrelay/m0/
          if-no-files-found: error
          retention-days: 14
```

- [ ] **Step 2: Protect the documented CI contract with a test**

Add a contract test asserting the workflow contains checkout/setup-node/setup-python/upload-artifact v7, `python scripts/verify_m0.py`, and `.boundrelay/m0/`.

- [ ] **Step 3: Run locally and push**

```bash
python scripts/verify_m0.py
git add .github/workflows/m0.yml tools/contracts/test_contracts.py
git commit -m "ci: verify M0 behavioral parity"
git push
```

- [ ] **Step 4: Verify the pushed revision**

Confirm the `M0 Verification / verify` job succeeds for the exact head SHA. Download the artifact and verify `verification-evidence.json.status == PASSED` and `verification-evidence.json.revision == <head SHA>`.

- [ ] **Step 5: Mark M0 complete in a separate commit**

Only after Step 4, update `.ai/delivery/current-scope.md`:

```markdown
## Active phase

M0 — Behavioral parity vertical slice complete and verified.

## Current evidence

- Command: `python scripts/verify_m0.py`
- CI workflow: `.github/workflows/m0.yml`
- Revision: `<exact green commit SHA>`
- Artifact: `m0-verification-<exact green commit SHA>`
```

Commit with:

```bash
git add .ai/delivery/current-scope.md
git commit -m "docs: record verified M0 completion"
```

Do not reuse evidence after any affected code, contract, fixture, or workflow change.

---

## Plan Self-Review

- **Spec coverage:** Tasks 1–7 cover M0 scope, language-neutral authority, offline execution, invalid-route failure, schemas, traces, parity, local verification, CI, documentation, and revision-bound evidence.
- **Scope exclusions:** The plan contains no real provider, Go, database, checkpointing, MCP, framework adapter, queue, web UI, or plugin system.
- **Type consistency:** Route names, modes, statuses, event types, and failure code are identical across schema, TypeScript, Python, and parity boundaries.
- **Command consistency:** Local and CI authority is `python scripts/verify_m0.py`; the parity subcommand is `python -m tools.parity.verify_m0`.
- **Completion boundary:** M0 remains incomplete until green evidence is tied to the pushed head revision.
