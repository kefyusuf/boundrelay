# Fault-Injection Labs

Runnable exercise packs, one per lesson (M0–M5). Every exercise replays a declared fault from the machine-readable failure matrix (`fixtures/failure-matrix.yaml`) through the lesson's own scripted controls — no new fault machinery, everything offline. Expected responses are the matrix's; a coverage test (`tools/contracts/test_v1_labs.py`) proves every matrix row appears in exactly one lab.

## How to run

Install the lessons you need (see the root README's per-milestone sections), then run the exercises' commands from the repository root. To watch any exercise's trace afterwards, use the trace inspector:

```bash
python tools/inspector.py --trace <trace>.jsonl [--result <result>.json]
```

## Lab index

| Lab | Lesson | Fault rows |
|---|---|---|
| [Lab 0 — Routing fail-closed](lab-m0-routing.md) | M0 support-triage | M0-F1 |
| [Lab 1 — Tool-loop failures](lab-m1-tool-loop.md) | M1 order-investigation | M1-F1…F4 |
| [Lab 2 — Handoff boundaries](lab-m2-handoff.md) | M2 support-handoff | M2-F1…F3 |
| [Lab 3 — Fan-out/fan-in](lab-m3-fanout.md) | M3 order-brief | M3-F1…F4 |
| [Lab 4 — Crash and recovery](lab-m4-recovery.md) | M4 order-brief-recovery | M4-F1…F5 |
| [Lab 5 — Effects and approval](lab-m5-effects.md) | M5 order-closure | M5-F1…F4 |

## Format

Each lab lists its exercises as: **command** → expected observation (the matrix row's response) → discussion questions. The TypeScript CLI is shown; the Python module runs the same grammar (swap `npx tsx src/cli.ts` for `python -m boundrelay_m<N>` with `PYTHONPATH` set, or use the mapping/Go equivalents where available). Unit-level rows (no case) point at the proving test to run instead of a CLI command.
