# M7 Go Parity Design

- **Date:** 2026-11-04
- **Status:** Proposed — awaiting owner review and written-design approval
- **Milestone:** M7 — Go parity
- **Project:** BoundRelay
- **Baseline:** merged M6 at `bbc39ef6ab8fb5b72f5105e0f272e33125e92d05`
- **Decision:** [D-018](../../decisions/D-018-m7-go-parity-stable-lessons.md), proposed
- **Depends on:** [foundation design](../../design/2026-09-02-foundation-design.md), D-001 through D-017, completed M0–M6 verification, [D-003](../../decisions/D-003-language-rollout.md)

## 1. Purpose and design brief

M7 adds Go as the third language per D-003: contract stability is now proven (M0–M6 certified with revision-bound evidence), so the stable lessons can be ported idiomatically. The roadmap requires: stable lessons implemented idiomatically in Go, shared contracts and invariants preserved, demonstration of contexts, cancellation, bounded concurrency, and explicit errors, and Go added to cross-language parity CI.

This proposed design pins M7's scope to the two contract-stable lessons that exercise exactly the roadmap's Go showcase points — **M0** (`support-triage` deterministic-vs-model routing) and **M3** (`order-brief` bounded fan-out/fan-in with concurrency limits) — while the remaining lessons (M1, M2, M4, M5, M6 evaluator/chaos tooling) stay TypeScript/Python-only and are deferred to later decisions. Porting all six lessons at once would make the milestone unreviewable and defer none of the parity questions that M0+M3 already settle.

The teaching objective is:

> The same schemas, event contracts, and invariants must hold in Go — expressed through contexts, bounded goroutine admission, and explicit error values, not through a line-by-line translation of the TypeScript or Python sources.

This proposed design preserves offline execution, shared behavioral contracts, and exact-revision evidence. Go joins the existing parity discipline: same goldens, same event envelopes, same business projections, its own idiomatic test suite (`go test`), and a CI workflow slot.

## 2. Approaches considered

| Approach | Benefit | Limit | Choice |
|---|---|---|---|
| Go parity for M0 + M3 (contract-stable showcase pair) | Proves the full parity chain (schemas, traces, goldens, CI) on deterministic and concurrent scenarios; contexts + bounded admission demonstrated where they are idiomatic | Leaves four lessons TS/PY-only until a later decision | Recommended |
| Go parity for all six lessons at once | Completes D-003 in one milestone | Very large diff; parity questions repeat per lesson; review cost explodes | Rejected for M7 |
| Go parity for M0 only | Smallest slice | Does not demonstrate contexts/bounded concurrency — the roadmap's explicit Go rationale | Rejected |

### Teaching sequence

Follow D-005: run the M0/M3 golden flows in TS/PY first, then express the same contracts in Go — strict JSON decoding into typed structs, `context.Context` threading, a bounded semaphore admission loop, sentinel error values per failure class — and compare Go's normalized results and event sequences against the same goldens. The lesson explains where Go is more explicit (context propagation, error values, channel-based limits) and where nothing changes (the contracts).

## 3. Scope and module layout

Go code lives in a single module at `go/` (`go.mod` module `github.com/kefyusuf/boundrelay/go`, Go >= 1.25, zero third-party dependencies — the standard library covers JSON, YAML-equivalent fixture loading via checked-in JSON fixtures, hashing, and testing):

```text
go/
├── go.mod, go.sum (no third-party requires)
├── contracts/        typed structs mirroring the shared schemas (events, results, attribution)
├── internal/m0/      support-triage runtime: loaders, router, fake model, trace sink, CLI
├── internal/m3/      order-brief runtime: loaders, bounded executor, collector, synthesizer, trace sink, CLI
└── internal/parity/  golden comparison helpers shared by both runtimes' tests
```

- CLIs mirror the TS/PY grammars exactly: `go run ./internal/m0/cmd --mode … --case … --trace …` and `go run ./internal/m3/cmd --mode … --case … --trace …`, emitting one nonblank JSON result line (exit 0 for domain outcomes, 2 for tooling errors).
- Strict decoding: `json.Decoder` with `DisallowUnknownFields`, finite-number guards mirroring the lessons' bounded-JSON rules, explicit sentinel errors (`ErrInvalidRoute`, `ErrUnknownWorker`, `ErrInvalidWorkerOutput`, `ErrWorkerExecutionFailed`) mapped to the same failure codes.
- Concurrency (M3): admission through a weighted semaphore over goroutines, `context.Context` for cancellation of the in-flight set on fatal errors (mirroring M3's drain semantics — never M4 semantics), slot ownership proven by instrumented worker bodies exactly like the TS/PY executor probes.
- Traces: the shared envelope at version `1.0`, same payload rules, `source: "go"`.

## 4. Contracts and attribution

Go consumes the same closed schemas: results carry the required `attribution` block (fixture tables read from the six scenario YAML files via a checked-in JSON projection per Go lesson — `fixtures/attribution/<scenario>.go.json` generated by a reviewed command, because Go's standard library has no YAML parser and adding one is excluded). Event surface, event sequences, business projections, and goldens are identical to TS/PY: `fixtures/goldens/` gains `languages: ['typescript','python','go']` semantics for the M0/M3 cases — the golden files themselves stay unchanged; the evaluator's language set gains `go` for those scenarios.

No M6 evaluator or chaos changes beyond the language-set extension for M0/M3: `tools/evaluate.py` learns `--languages` and runs Go flows for `support-triage` and `order-brief`; the failure matrix rows for M0/M3 gain Go proof identities in the Go test suite.

## 5. Parity, tests, and CI

- Go unit tests (`go test ./...`) mirror the lesson invariants: schema-valid results, event-lifecycle assertions, once-only invocation, bounded admission (max 2 active worker bodies, instrumented), deterministic routing, invalid-route fail-closed.
- Parity: Go's normalized results and event sequences must equal the existing TS/PY goldens for all M0/M3 cases (13 keys: 7 + 6). The M6 evaluator extends to three languages for those cases.
- New authority: `python scripts/verify_m7.py` — clean starting revision → invoke `verify_m6.py` once (M6→M0 chain) → `go vet ./...` + `go test ./...` → Go CLI flows for all 13 M0/M3 cases vs goldens (3-language comparison) → publish `.boundrelay/m7/verification-evidence.json` on an unchanged HEAD.
- CI: `.github/workflows/m7.yml` adds `actions/setup-go` (Go version from a `go/GO_VERSION` pin file) and runs the same authority; artifact `m7-verification-<revision>`.

## 6. Invariants and completion criteria

1. Go implements M0 and M3 idiomatically — no line-by-line translation claims.
2. Shared schemas/contracts unchanged; Go decodes them strictly and fails closed.
3. `context.Context` cancellation mirrors M3's fatal-drain semantics only.
4. Bounded admission ≤ 2 with instrumented overlap proof.
5. Sentinel error values map 1:1 to the declared failure codes.
6. All 13 M0/M3 case keys: TS, PY, and Go normalized projections identical; goldens untouched.
7. Attribution identical across the three languages (same fixture tables).
8. `go vet` clean; `go test` green; zero third-party dependencies.
9. M6 evaluator runs three languages for M0/M3 without regression to TS/PY-only cases.
10. M0–M6 gates remain valid; M7 evidence is bound to the current candidate revision.

(Invariants 11–20 are completed at plan time, mapping to implementation tasks.)

## 7. Explicit exclusions

M7 does not port M1, M2, M4, M5, the evaluator, or chaos to Go; no cgo, no third-party Go dependencies, no YAML parser, no goroutine-per-case framework, no trace inspector, no real providers. The remaining lessons' Go ports are separate later decisions (M8+/v1.0 track).

## 8. Written-design review gate

This design is **Proposed**. The owner's written-design approval — covering the M0+M3 scope, the `go/` module layout, the attribution-fixture projection, the evaluator's language-set extension, and the M7 authority — is required before the implementation plan is drafted. Design acceptance alone does not authorize product implementation.

