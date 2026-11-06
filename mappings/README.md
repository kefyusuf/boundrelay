# Framework mappings

Non-authoritative framework mappings per [D-008](../docs/decisions/D-008-framework-policy.md): canonical lessons rebuilt on third-party agent frameworks to expose what each framework buys, what must be re-implemented inside it anyway, what it silently changes, and how to leave. Mappings never feed the goldens, the failure matrix, or the M0–M7 gates; they read checked-in artifacts only and are dependency-isolated (each mapping's contracts test in `tools/contracts/` fails closed on any reference outside the mapping).

| Mapping | Framework (exact pin) | Lesson | Contracts | Status |
|---|---|---|---|---|
| [langgraph-m3](langgraph-m3/README.md) | LangGraph `1.2.20` | M3 `order-brief` (bounded fan-out/fan-in) | `tools/contracts/test_m8_contracts.py` | M8 (merged) |
| [openai-m1](openai-m1/README.md) | OpenAI Agents SDK (Python) `0.24.0` | M1 `order-investigation` (bounded tool loop) | `tools/contracts/test_p5_contracts.py` | P5 (v1.0 track) |
| [adk-m2](adk-m2/README.md) | Google ADK (Python) `2.13.0` | M2 `support-handoff` (router→handoff, 0.80 confidence policy) | `tools/contracts/test_p5b_contracts.py` | P5 (v1.0 track) |
| [mastra-m3](mastra-m3/README.md) | Mastra (TypeScript) `@mastra/core 1.82.0` | M3 `order-brief` (bounded fan-out/fan-in) | `tools/contracts/test_p5c_contracts.py` | P5 (v1.0 track) |
| [eino-m3](eino-m3/README.md) | Eino (Go) `github.com/cloudwego/eino v0.9.22` | M3 `order-brief` (bounded fan-out/fan-in) | `tools/contracts/test_p5d_contracts.py` | P5 (v1.0 track) |

## Running a mapping

Each Python mapping carries its own `python/` package (`boundrelay-m3-langgraph`, `boundrelay-m1-openai`, `boundrelay-m2-adk`), an exact-pin `requirements-dev.txt` installed at setup only, and a unittest suite. The TypeScript mapping (`mastra-m3`) carries its own `typescript/` npm package with a committed lockfile and a vitest suite. The Go mapping (`eino-m3`) carries its own `go/` module with the framework pinned in `go.mod`/`go.sum` and a `go test` suite. See the mapping README for the exact commands; the shared shape is:

```bash
PYTHONPATH=mappings/<mapping>/python/src .venv/Scripts/python.exe -m unittest discover -s mappings/<mapping>/python/tests -t mappings/<mapping>/python/tests
PYTHONPATH=mappings/<mapping>/python/src .venv/Scripts/python.exe -m <package>.cli --case <case-id> --trace <native-stream-file>
cd mappings/mastra-m3/typescript && npm ci && npm test
npx tsx src/cli.ts --case <case-id> --trace <native-stream-file>
cd mappings/eino-m3/go && go test ./...
go run ./cmd --case <case-id> --trace <native-stream-file>
```

Framework runs are fully offline: the framework's execution machinery drives deterministic, scripted model/tool boundaries rebuilt from the canonical fixtures — no LLM calls, no network.
