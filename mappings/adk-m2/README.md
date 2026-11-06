# P5b Mapping — Google ADK (Python) × M2 `support-handoff`

Non-authoritative framework mapping per [D-008](../../docs/decisions/D-008-framework-policy.md): the M2 router→handoff flow rebuilt on Google ADK (`google-adk==2.13.0`, import package `google.adk`) to expose what the framework buys, what must be re-implemented inside it anyway, what it silently changes, and how to leave. The mapping never feeds the goldens, the failure matrix, or the M0–M7 gates; it reads checked-in artifacts only (`fixtures/goprojections/support-handoff/`, `fixtures/goldens/support-handoff/`, `contracts/routing/`, `contracts/handoffs/`, `contracts/results/handoff-result.schema.json`) and emits ADK's native event stream — event-envelope trace parity is explicitly out of scope.

## Setup and run

The SDK is pinned exactly (`python/requirements-dev.txt`: `google-adk==2.13.0` plus the shared `jsonschema[format]==4.26.0` pin) and is installed at setup only; runs are offline — a custom `BaseLlm` implementation replays the M2 fake-model decision and is injected straight into the `LlmAgent`, so `Runner`/auto-flow machinery executes with zero network and zero LLM calls.

```bash
# repo venv already carries the pin (`uv pip install google-adk`); or a mapping-local venv:
python -m venv .venv-p5b && .venv-p5b/Scripts/python -m pip install -r mappings/adk-m2/python/requirements-dev.txt
# suite (repo venv python, mapping src on PYTHONPATH):
PYTHONPATH=mappings/adk-m2/python/src .venv/Scripts/python.exe -m unittest discover -s mappings/adk-m2/python/tests -t mappings/adk-m2/python/tests
# one case through the ADK Runner (one JSON result line on stdout; exit 0 domain, 2 tooling):
PYTHONPATH=mappings/adk-m2/python/src .venv/Scripts/python.exe -m boundrelay_m2_adk.cli --case model-technical-handoff --trace .boundrelay/manual/p5b-native-trace.jsonl
```

All five parity cases reproduce the M2 goldens' `result_projection` (router_mode, proposed/selected route, receiver, `fallback_applied`, `specialist_invoked`, failure code, attribution) — proven by `python/tests/test_parity.py::FiveCaseParityTests` (deep-equal minus `run_id`/`trace_path`, schema-valid against `contracts/results/handoff-result.schema.json`).

## D-008 question 1 — What the framework provides

The agent loop (`LlmAgent` + `Runner.run_async` over the auto flow: model turn → function-call execution → tool response → next model turn until a text-only turn ends the invocation), the model boundary as a first-class abstraction (`BaseLlm.generate_content_async` — the seam the scripted replay plugs into; `LlmResponse`/genai `Content` parts are the model's output contract), typed function tools (`FunctionTool` with an auto-generated declaration; the framework injects a `ToolContext` by parameter name), the workflow-agent shape (`BaseAgent` subclass — the model-less agent the code-mode router uses, still driven by the same Runner), the run/session/event machinery (`Runner` + `InMemorySessionService`; the native `Event` stream is written verbatim to `--trace`), and the error channel (a tool exception becomes a framework `Event` with `error_code`/`error_message`, then the original exception propagates out of `run_async` — the seam the taxonomy recovers through).

Proof: `python/tests/test_parity.py` drives all five cases through the real Runner and shows the native events (`function_call` → `function_response` for model mode; `code_router`-authored events for code mode; a framework error event on the tool-failure path); `test_offline.py::ScriptedModelPurityTests` proves `ScriptedRouterModel` is a real `BaseLlm` with no client.

## D-008 question 2 — What remains application responsibility

The whole routing/handoff discipline: the scripted model (`mapping.ScriptedRouterModel` — ADK has no deterministic replay primitive), the M2 failure taxonomy at the boundary (`mapping.execute_handoff` validates the decision against the checked-in route-decision contract → `INVALID_ROUTE_DECISION`, validates the handoff envelope against the support-handoff contract → `HANDOFF_CONTEXT_INVALID`, resolves the receiver directory → `HANDOFF_RECEIVER_UNAVAILABLE`; every failure raises before the receiver is invoked), the 0.80 confidence policy (`apply_confidence_policy` — the framework has no confidence concept at all), the sender-intent vs receiver-input envelope (built by the boundary, validated before dispatch), receiver availability (fixture-driven: `unavailable_receivers` removes the receiver before resolution), invocation accounting (the `RunLedger` records the classify step and each receiver dispatch), and attribution (M2 rules: `classify` priced `model_decision` in model mode and `route` in code mode; `receiver.<name>` priced `handoff`).

Proof: `python/tests/test_taxonomy.py` (the fallback boundary 0.79/0.80/0.81 replayed through the real machinery; `INVALID_ROUTE_DECISION` with a null selection; zero-dispatch proofs — spy receiver directories never see an invocation on either handoff failure), `python/tests/test_attribution.py` (mode-dependent pricing, totals = sum).

## D-008 question 3 — What becomes hidden or changes

The auto flow re-invokes the model after every tool response — even with `tool_context.actions.escalate = True` (verified against 2.13.0), so the M2 one-decision flow becomes a two-turn loop: the mapping scripts the wrap-up turn and excludes it from attribution (the framework's second turn is unpriced by the domain accounting; `usage_metadata` exists only as scripted telemetry — the M2 result schema carries no token fields). The failure channel is rewritten: a tool exception is first converted into a framework error `Event` (`error_code` = the exception class name), then the exception propagates — the mapping walks the cause chain (`classify_run_exception`) to recover the taxonomy; the code-mode router (custom `BaseAgent` root) propagates without an error event, an asymmetry that is framework-native. Agent names must be Python identifiers (`support_router`), so the hyphenated M2 receiver names cannot be agent names. Most importantly, ADK's flagship multi-agent transfer cannot express the M2 semantics: `transfer_to_agent` forwards session history, not a validated `receiver_input` envelope, and the transfer itself is the dispatch — zero dispatch on `HANDOFF_CONTEXT_INVALID` is structurally impossible there. The mapping therefore realizes receivers as deterministic tool functions behind the explicit handoff tool (the documented mapping choice), which keeps the golden receiver names (`billing-specialist`) and the exact M2 check order (validate → resolve → dispatch) intact. Telemetry is SDK-shaped: the ADK Event stream replaces the shared event envelope, and runs are driven per-invocation (`asyncio.run` around one `Runner` pass) with ADK's duplicate error logging suppressed while the mapped failure is published as the terminal record.

Proof: `python/tests/test_taxonomy.py` (policy boundary, envelope validation, zero dispatch), `python/tests/test_parity.py::NativeTraceTests` (the error event carries the mapped failure; the code-mode failure ends the native stream at the classify event), `python/tests/test_offline.py` (the machinery completes with every HTTP client constructor patched to explode and no Google API key).

## D-008 question 4 — How to exit the abstraction

The mapping imports the canonical fixtures, goldens, and contract schemas only through their checked-in artifacts (`fixtures.py` reads `fixtures/goprojections/support-handoff/`, `fixtures/goldens/support-handoff/`, `contracts/routing/route-decision.schema.json`, `contracts/handoffs/support-handoff.schema.json`; tests validate against `contracts/results/handoff-result.schema.json`). Nothing outside `mappings/adk-m2/` references the package or the SDK: `tools/contracts/test_p5b_contracts.py` fails closed on any `google-adk`/mapping token or any bare `google` import under `lessons/`, `contracts/`, `tools/`, `scripts/`, `go/` outside a precise allowlist. Deleting `mappings/` leaves every lesson, gate, golden, and evidence path intact — the canonical lesson (`lessons/02-routing-handoff/`) remains the source of truth and the exit path.

Proof: `tools/contracts/test_p5b_contracts.py` (isolation scan, manifest pins, parity keys) and `python/tests/test_offline.py` (every HTTP client constructor patched to explode; the Runner machinery completes all five case shapes anyway, with no `GOOGLE_API_KEY`).

## Files

| File | Responsibility |
|---|---|
| `python/pyproject.toml` | Package `boundrelay-m2-adk`; no runtime deps |
| `python/requirements-dev.txt` | Exact `google-adk==2.13.0` + shared `jsonschema` pin |
| `python/src/boundrelay_m2_adk/fixtures.py` | Strict fixture/golden/schema loading (checked-in artifacts only) |
| `python/src/boundrelay_m2_adk/mapping.py` | ADK wiring: scripted `BaseLlm`, handoff tool boundary, policy, code-mode `BaseAgent`, taxonomy mapping |
| `python/src/boundrelay_m2_adk/results.py` | M2-schema result assembly + structural validation |
| `python/src/boundrelay_m2_adk/attribution.py` | Attribution from fixture tables (M2/M6 rules, mode-priced) |
| `python/src/boundrelay_m2_adk/cli.py` | `--case/--trace`; exit 0 domain, 2 tooling |
| `python/tests/` | Mapping suite (fixtures, parity, taxonomy, offline, attribution, results, CLI) |
