# Lab 4 — Crash and recovery (M4 order-brief-recovery)

**Invariant under attack:** write-ahead checkpoints survive real process exits; resume never re-executes recorded outcomes; corruption fails closed; cancellation is a domain outcome.

All exercises are two-phase CLI runs sharing one `--state-dir`.

## Exercise 1 — M4-F1: crash window (matrix row `M4-F1`)

```bash
cd lessons/04-durable-state-recovery/typescript
npx tsx src/cli.ts --case parallel-crash-resume --trace p1.jsonl --state-dir state     # exit 2, no result
npx tsx src/cli.ts --case parallel-crash-resume --trace p2.jsonl --state-dir state --resume   # exit 0, SUCCEEDED
```

**Expected:** phase 1 exits `2` with **no result line** and a durable state document (order+payment recorded); phase 2 resumes and completes `SUCCEEDED` — order and payment were invoked exactly once *across both processes*.

Inspect the crashed phase's prefix:

```bash
python tools/inspector.py --trace p1.jsonl
```

The trace ends after the last `checkpoint.saved` — no terminal event; the state document is the only testimony.

## Exercise 2 — M4-F3: corrupt state (matrix row `M4-F3`)

Run the canonical corrupt case: the fixtures tamper a copied state document deterministically (payment outcome flipped, digest stale), then resume against it:

```bash
npx tsx src/cli.ts --case parallel-corrupt-state --trace c1.jsonl --state-dir state2
python tools/evaluate.py --scenario order-brief-recovery --case parallel-corrupt-state
```

**Expected:** the resume attempt exits `2` with no result line and **zero worker invocations** — the digest mismatch is evidence, not a restart prompt.

## Exercise 3 — M4-F4: cancellation (matrix row `M4-F4`)

```bash
npx tsx src/cli.ts --case parallel-cancel-resume --trace k1.jsonl --state-dir state3    # CANCELLED, exit 0
npx tsx src/cli.ts --case parallel-cancel-resume --trace k2.jsonl --state-dir state3 --resume  # SUCCEEDED
```

**Expected:** phase 1 returns a `CANCELLED` result line (domain outcome, no failure code); resume completes only the remaining workers.

## Exercise 4 — `M4-F2` / `M4-F5`: unit rows

```bash
python -m unittest tools.parity.test_m4_verification_safety -v
python -m unittest discover -s lessons/04-durable-state-recovery/python/tests -p "test_recovery.py" -v
```

## Discussion

1. Why is the crash phase's exit code `2` (tooling) while the cancelled phase's is `0` (domain)? What would callers conflate otherwise?
2. The digest lives inside the state document and covers its own body. What attack does the self-digest stop that a side-car checksum would not?
3. Recorded failures are never re-executed on resume. When is that the wrong policy, and what would it take to change it safely? (Hint: idempotency keys — Lab 5.)
