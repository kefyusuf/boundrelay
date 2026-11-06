# P5 Mapping — OpenAI Agents SDK (Python) × M1 `order-investigation`

Non-authoritative framework mapping per [D-008](../../docs/decisions/D-008-framework-policy.md): the M1 bounded single-agent tool loop rebuilt on the OpenAI Agents SDK (`openai-agents==0.24.0`, import package `agents`) to expose what the framework buys, what must be re-implemented inside it anyway, what it silently changes, and how to leave. The mapping never feeds the goldens, the failure matrix, or the M0–M7 gates; it reads checked-in artifacts only (`fixtures/goprojections/order-investigation/`, `fixtures/goldens/order-investigation/`, `contracts/tools/`, `contracts/results/tool-loop-result.schema.json`) and emits the SDK's native run-item telemetry — event-envelope trace parity is explicitly out of scope.

## Setup and run

The SDK is pinned exactly (`python/requirements-dev.txt`: `openai-agents==0.24.0` plus the shared `jsonschema[format]==4.26.0` pin) and is installed at setup only; runs are offline — a custom `Model` implementation replays the M1 fake-model turns and is injected through `RunConfig`'s model/model-provider override, so `Agent`/`Runner` machinery executes with zero network and zero LLM calls.

```bash
# repo venv already carries the pin (`uv pip install openai-agents`); or a mapping-local venv:
python -m venv .venv-p5 && .venv-p5/Scripts/python -m pip install -r mappings/openai-m1/python/requirements-dev.txt
# suite (repo venv python, mapping src on PYTHONPATH):
PYTHONPATH=mappings/openai-m1/python/src .venv/Scripts/python.exe -m unittest discover -s mappings/openai-m1/python/tests -t mappings/openai-m1/python/tests
# one case through the SDK Runner (one JSON result line on stdout; exit 0 domain, 2 tooling):
PYTHONPATH=mappings/openai-m1/python/src .venv/Scripts/python.exe -m boundrelay_m1_openai.cli --case agent-delayed-shipment --trace .boundrelay/manual/p5-native-trace.jsonl
```

All eight parity cases reproduce the M1 goldens' `result_projection` (mode, status, answer, failure code, `model_steps`, `tokens_used`, `tool_invocations`, attribution) — proven by `python/tests/test_parity.py::EightCaseParityTests` (deep-equal minus `run_id`/`trace_path`, schema-valid against `contracts/results/tool-loop-result.schema.json`).

## D-008 question 1 — What the framework provides

The agent loop itself (`Agent` + `Runner.run_sync` with automatic turn cycling until a final output), typed function tools (`FunctionTool` with a JSON-schema parameter contract and structured output items), the model boundary as a first-class abstraction (`Model`/`ModelProvider` — the seam our scripted replay plugs into via `RunConfig.model`/`model_provider`), SDK usage accounting (`ModelResponse.usage`, aggregated per run in `raw_responses`), the native run-item telemetry (`ToolCallItem`, `ToolCallOutputItem`, `MessageOutputItem` — written verbatim to `--trace`), and the turn budget (`max_turns`, enforced by the SDK's own loop-top check).

Proof: `python/tests/test_parity.py` drives all eight cases through the real Runner; `NativeTraceTests` in the same file shows the native items (`ToolCallItem` → `ToolCallOutputItem` → `MessageOutputItem`); `test_budgets.py::MaxTurnsExceededIntegrationTests` proves the SDK itself raises `MaxTurnsExceeded` when turns run out.

## D-008 question 2 — What remains application responsibility

The whole bounded-loop discipline: the scripted model (`mapping.ScriptedAgentModel` — the SDK has no deterministic replay primitive; the ledger, not the SDK, owns `model_steps`/`tokens_used`), the M1 failure taxonomy (`mapping.classify_run_exception` maps SDK exceptions onto the closed failure codes; the closed argument validation re-implemented inside each tool via the checked-in `contracts/tools` schemas), the budget checkpoints (token budget checked at the M1 point — after the model turn, before the decision dispatch — because the SDK has no token budget at all), invocation accounting (the ledger increments counters pre-invocation so timeouts still price the attempt), and attribution (same fixture tables, `attribution.build_attribution`).

Proof: `python/tests/test_taxonomy.py` (UNKNOWN_TOOL / INVALID_TOOL_ARGUMENTS / TOOL_TIMEOUT / TOOL_EXECUTION_FAILED with exact counters; `classify_run_exception` proven against the SDK's `ModelBehaviorError "...not found in agent..."` and `UserError` tool-wrapping with cause-chain resolution), `python/tests/test_attribution.py` (table × attempts, totals = sum, golden totals 107/8/5).

## D-008 question 3 — What becomes hidden or changes

The SDK's exception channel rewrites tool failures: a tool exception is wrapped in `UserError("Error running tool ...")` (unless the tool's `failure_error_function` is disabled — we disable it, or the SDK would convert failures into model-visible error strings and keep looping), and an unknown tool name becomes `ModelBehaviorError` — both must be translated by cause-chain walking to recover the taxonomy. The token budget simply does not exist in the framework: `max_turns` bounds turns only, so the token checkpoint lives in the model boundary. Turn semantics differ: an SDK "turn" bundles the model call and its tool executions, so the M1 pre-invocation step check had to move inside the tools (a tool at the last allowed step never executes — the parity counters prove it). Telemetry is SDK-shaped: run items replace the shared event envelope, and failed runs expose only a terminal exception record (trace parity excluded by design). Usage accounting is SDK-owned but reconciled: the mapping cross-checks its scripted-usage ledger against `raw_responses` and fails as tooling on disagreement.

Proof: `python/tests/test_taxonomy.py::ClassifyTests` (the `UserError` wrapper chain and `ModelBehaviorError` probe), `python/tests/test_budgets.py` (pre-invocation step checkpoint counters 2/50/1; token checkpoint 2/75/1; SDK `MaxTurnsExceeded` integration), `python/tests/test_parity.py` (the counters reproduce the goldens exactly — the checkpoints are placed where M1 placed them).

## D-008 question 4 — How to exit the abstraction

The mapping imports the canonical fixtures, goldens, argument schemas, and result schema only through their checked-in artifacts (`fixtures.py` reads `fixtures/goprojections/order-investigation/`, `fixtures/goldens/order-investigation/`, and `contracts/tools/*.json`; tests validate against `contracts/results/tool-loop-result.schema.json`). Nothing outside `mappings/openai-m1/` references the package or the SDK: `tools/contracts/test_p5_contracts.py` fails closed on any `openai-agents`/mapping token or any bare `agents`/`openai` import under `lessons/`, `contracts/`, `tools/`, `scripts/`, `go/` outside a precise allowlist. Deleting `mappings/` leaves every lesson, gate, golden, and evidence path intact — the canonical lesson (`lessons/01-bounded-tool-loop/`) remains the source of truth and the exit path.

Proof: `tools/contracts/test_p5_contracts.py` (isolation scan, manifest pins, parity keys) and `python/tests/test_offline.py` (every HTTP client constructor patched to explode; the Agent/Runner machinery completes all case shapes anyway, with no `OPENAI_API_KEY`).

## Files

| File | Responsibility |
|---|---|
| `python/pyproject.toml` | Package `boundrelay-m1-openai`; no runtime deps |
| `python/requirements-dev.txt` | Exact `openai-agents==0.24.0` + shared `jsonschema` pin |
| `python/src/boundrelay_m1_openai/fixtures.py` | Strict fixture/golden/schema loading (checked-in artifacts only) |
| `python/src/boundrelay_m1_openai/mapping.py` | SDK wiring: scripted `Model`/provider, function tools, budget checkpoints, taxonomy mapping |
| `python/src/boundrelay_m1_openai/results.py` | M1-schema result assembly + structural validation |
| `python/src/boundrelay_m1_openai/attribution.py` | Attribution from fixture tables (M6 rules) |
| `python/src/boundrelay_m1_openai/cli.py` | `--case/--trace`; exit 0 domain, 2 tooling |
| `python/tests/` | Mapping suite (fixtures, parity, taxonomy, budgets, offline, attribution, results, CLI) |
