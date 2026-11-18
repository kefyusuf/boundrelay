# D-020 — v1.0 Track: Full Go Parity (P4) and the Framework Mapping Set (P5)

- **Status:** Accepted
- **Date:** 2026-11-18

## Context

M8 is integrated and certified on main. D-018 scoped Go to the M0/M3 showcase pair and explicitly deferred the M1/M2/M4/M5 ports to "separate later decisions on the M8+/v1.0 track"; D-019 bound M8 to a single LangGraph×M3 mapping and explicitly kept the other frameworks — including the Go/Eino mapping — outside M8. The roadmap's v1.0 track then delivered those deferrals as packages P4 and P5 (PRs #35–#42), but no decision record was written for either package. Three documented statements therefore drifted against the tree, and one authority extension shipped unrecorded:

- README still described M1/M2/M4/M5 as "TS/PY-only, deferred to later decisions";
- the ROADMAP's P4 row anticipated a "`verify_m9.py`-style authority extension" that never materialized as a separate script;
- the ROADMAP's P5 row listed "LangGraph×M4", which does not exist — the LangGraph mapping shipped as LangGraph×M3 under M8 (D-019).

## Decision

Record the v1.0 track's two deferred packages as one decision:

- **P4 — Go parity for all lessons.** Go runtimes for M1, M2, M4, and M5 live in `go/internal/` (PRs #35–#38), extending D-018's showcase-pair decision. This supersedes D-018's "M1, M2, M4, M5 … remain TypeScript/Python-only" line: all 38 canonical case keys now reach three-language golden parity (TS == PY == Go) against the unchanged goldens, with the same zero-dependency Go module, strict JSON decoding, sentinel failure codes, and typed contract structs.
- **Authority.** The extension lives inside the M7 authority (`tools/parity/verify_m7.py`, `THREE_LANGUAGE_CASES=38`) rather than a separate `verify_m9.py` wrapper; this decision records that supersession explicitly. The M7→M0 chain, revision-bound evidence, unchanged-HEAD publication check, and fail-closed semantics are unchanged; the M7 language probes now cover real M1/M2/M4/M5 Go case flows, and the M6 evaluator requires all 38 cases three-language.
- **P5 — the framework mapping set.** Four mappings extend D-019's single-mapping pattern under the same D-008 isolation rules, one per package increment (PRs #39–#42): OpenAI Agents SDK (Python)×M1 (P5a), Google ADK (Python)×M2 (P5b), Mastra (TypeScript)×M3 (P5c), and Eino (Go)×M3 (P5d). The ROADMAP's P5 row is corrected to these four shipped mappings; LangGraph×M3 already shipped under M8 and no LangGraph×M4 mapping is planned.
- **Verification.** Each mapping's contracts test in `tools/contracts/` (`test_p5*_contracts.py`) fails closed on dependency isolation, exact manifest pins, and canonical parity keys; each mapping suite runs fully offline against the canonical fixtures, and each Python contract test asserts the installed framework version against its exact pin. CI wiring for the P5 suites lands as the `p5.yml` workflow, running the same commands the mappings README documents.

## Consequences

- The decision index closes the D-018 deferral loop: "separate later decisions" is this record.
- The M7 evidence semantics change meaning: `THREE_LANGUAGE_CASES` and the evaluator's three-language count are 38, not 13; the README's M7 section is corrected accordingly.
- The P-track packages shipped as single reviewed PRs with revision-bound CI evidence rather than the full design → plan → implementation sequence used for M0–M8; this decision is the recorded retroactive scope for P4/P5 (P1–P3 shipped similarly under PRs #32–#34 with their own executable linkage tests).
- No canonical lesson, golden, failure matrix, or lower-milestone boundary is changed by this decision.

## Acceptance gate

The owner approved this record on 2026-11-18. No lower-milestone boundary is changed by this decision.
