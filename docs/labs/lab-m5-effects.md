# Lab 5 — Effects and approval (M5 order-closure)

**Invariant under attack:** approval gates the irreversible effect; the idempotency key bounds retries; the submit→confirm window is the only unsafe window; an unprovable effect stays UNKNOWN.

All exercises are multi-phase CLI runs sharing one `--state-dir` (the effect ledger lives at the state-dir root).

## Exercise 1 — M5-F1: approval rejection (matrix row `M5-F1`)

```bash
cd lessons/05-side-effects-approval/typescript
npx tsx src/cli.ts --case approval-rejected-no-effect --trace f1.jsonl --state-dir state1
```

**Expected:** exit `0`, `status: FAILED` / `APPROVAL_REJECTED`, **zero submissions** (the ledger file does not exist or is empty), the audit log records the rejection.

Check the audit:

```bash
cat state1/audit.jsonl
```

## Exercise 2 — M5-F2: submit-window crash, resolved by key lookup (matrix row `M5-F2`)

```bash
npx tsx src/cli.ts --case crash-submit-window-resolved --trace c1.jsonl --state-dir state2   # exit 2, crash after the ledger accepted
npx tsx src/cli.ts --case crash-submit-window-resolved --trace c2.jsonl --state-dir state2 --resume   # exit 0
```

**Expected:** phase 1 crashes after the ledger recorded the effect but before the run recorded it; the resume **adopts** the recorded outcome (`reconciled: true`) and never re-submits — the ledger still holds exactly one record.

## Exercise 3 — M5-F3: unprovable effect (matrix row `M5-F3`)

```bash
npx tsx src/cli.ts --case sink-unavailable-unknown --trace u1.jsonl --state-dir state3      # crash phase, exit 2
npx tsx src/cli.ts --case sink-unavailable-unknown --trace u2.jsonl --state-dir state3 --resume   # UNKNOWN, exit 0
```

**Expected:** the resume terminates `UNKNOWN` — a domain result line, exit `0`, no failure code, and **no flattening** into success or failure.

## Exercise 4 — M5-F4: duplicate key suppression (matrix row `M5-F4`)

```bash
npx tsx src/cli.ts --case duplicate-key-suppressed --trace d1.jsonl --state-dir state4
npx tsx src/cli.ts --case duplicate-key-suppressed --trace d2.jsonl --state-dir state4   # second fresh run, same ledger
```

**Expected:** the second run adopts the recorded outcome (`duplicate: true`); the ledger still holds exactly one record — the naive retry was absorbed by the key.

Inspect the UNKNOWN run:

```bash
python tools/inspector.py --trace u2.jsonl
```

## Discussion

1. `UNKNOWN` is a terminal status, not a failure. What would break if the run reported `FAILED` instead — and who would be accountable for the refund that may or may not have happened?
2. The submit marker is written *before* the ledger call. What does the write-ahead ordering buy that a post-confirmation marker would not?
3. The naive retry in the mapping's teaching demo attempts a second submission and the key absorbs it. What does the key *not* protect against, and which milestone's machinery would? (Hint: real networks.)
4. Approval binds to the payload digest. What happens to a granted approval when the refund amount changes — and why is re-approval the only path?
