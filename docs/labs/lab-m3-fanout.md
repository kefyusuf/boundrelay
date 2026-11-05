# Lab 3 — Fan-out/fan-in (M3 order-brief)

**Invariant under attack:** bounded admission (1 sequential / 2 parallel), once-only invocation, explicit partial failure, canonical merge order independent of completion order, and a single synthesis owner.

## Exercise 1 — M3-F1: declared worker failure (matrix row `M3-F1`)

```bash
cd lessons/03-parallel-fanout-fanin/typescript
npx tsx src/cli.ts --mode parallel --case parallel-partial-failure --trace f1.jsonl
```

**Expected:** exit `0`, `status: PARTIAL`, `missing_workers: ["delivery-status"]`, `failure_code: WORKER_EXECUTION_FAILED` on the failed outcome only, sibling outcomes intact, synthesis invoked once.

## Exercise 2 — M3-F2: invalid worker output (matrix row `M3-F2`)

```bash
npx tsx src/cli.ts --mode parallel --case parallel-invalid-output --trace f2.jsonl
```

**Expected:** exit `0`, `status: PARTIAL`, the payment outcome failed with `INVALID_WORKER_OUTPUT` — the raw invalid payload never appears in the trace or the brief.

## Exercise 3 — M3-F3: all workers failed (matrix row `M3-F3`)

```bash
npx tsx src/cli.ts --mode parallel --case parallel-all-failed --trace f3.jsonl
```

**Expected:** exit `0`, `status: FAILED` / `ALL_WORKERS_FAILED`, `synthesis_invoked: false`, brief `null` — no report is fabricated from zero evidence.

Inspect (watch the bounded overlap in the timeline):

```bash
python tools/inspector.py --trace f1.jsonl
```

## Exercise 4 — `M3-F4`: unexpected error drain (unit row, no CLI case)

Run the proving probes instead — the fatal error stops admission, drains entered workers, and propagates as a tooling failure:

```bash
python -m unittest tools.parity.test_m3_verification_safety -v
python -m unittest discover -s lessons/03-parallel-fanout-fanin/python/tests -p "test_executor.py" -v
```

## Discussion

1. `PARTIAL` is a success exit with explicit missing evidence. Why not fail the run when one read fails?
2. The brief's section order follows the canonical worker order, not completion order. Run `parallel-out-of-order` and compare briefs — why must completion order never choose report content?
3. The third worker waits while both slots are busy. What breaks in a framework that fans out uncapped? (See the LangGraph mapping's naive mode for the honest answer.)
