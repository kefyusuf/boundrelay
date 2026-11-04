# D-018 — M7 Go Parity for the Contract-Stable Showcase Pair

- **Status:** Proposed
- **Date:** 2026-11-04

## Context

M6 is integrated and certified on main. D-003 defers Go until contract stability: M0–M6 now hold that bar with revision-bound evidence and 38 language-agnostic goldens. The roadmap's M7 requires stable lessons idiomatically in Go, shared contracts preserved, demonstration of contexts, cancellation, bounded concurrency, and explicit errors, and Go added to cross-language parity CI.

Porting all six lessons at once would make M7 unreviewable. The showcase pair — M0 (deterministic-vs-model routing) and M3 (bounded fan-out/fan-in) — exercises every point the roadmap names for Go while settling all parity mechanics (schemas, traces, goldens, attribution, CI) on the two most contract-stable scenarios.

## Decision

Bound M7 to Go parity for **M0 and M3 only**:

- A single zero-dependency Go module at `go/` (Go >= 1.25, standard library only) with `internal/m0` and `internal/m3` runtimes, typed contract structs, and shared parity helpers.
- CLIs mirroring the TS/PY grammars; strict JSON decoding with `DisallowUnknownFields`; sentinel errors mapping 1:1 to the declared failure codes; traces on the shared `1.0` envelope with `source: "go"`.
- M3 concurrency via a bounded semaphore over goroutines with `context.Context` fatal-drain cancellation — mirroring M3's semantics, never M4's.
- Attribution tables projected to checked-in JSON per scenario (no YAML parser, no third-party deps); results carry the required attribution block identical to TS/PY.
- The M6 evaluator's language set gains `go` for `support-triage` and `order-brief`; goldens stay unchanged; all 13 M0/M3 case keys must match across three languages.
- The M7 authority `python scripts/verify_m7.py` chains `verify_m6.py` once (M6→M0), then runs `go vet` + `go test`, the 13 Go CLI flows against goldens, and publishes `.boundrelay/m7/verification-evidence.json` on an unchanged HEAD. CI adds `setup-go` with a pinned version.

M1, M2, M4, M5, the evaluator, and chaos remain TypeScript/Python-only; their Go ports are separate later decisions on the M8+/v1.0 track.

## Consequences

- The parity chain extends to three languages without touching any TS/PY behavior; lower gates are untouched.
- `fixtures/attribution/<scenario>.go.json` projections become reviewed artifacts regenerated only via a reviewed command.
- The M6 evaluator gains a `--languages` capability; TS/PY-only scenarios keep their two-language flows.
- The future M7 authority invokes M6, retaining the M6→M0 chain and current-revision evidence checks.
- cgo, third-party Go modules, YAML parsing in Go, Go ports of the remaining lessons, real providers, and shared-runtime extraction remain outside M7.

## Design

[M7 Go Parity Design](../superpowers/specs/2026-11-04-m7-go-parity-design.md)

## Acceptance gate

This decision is proposed together with the written design. Owner approval of both is required before detailed implementation planning; reviewed-plan approval and execution-method selection are required before product implementation. No lower-milestone boundary is changed by this decision.
