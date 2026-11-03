# Lesson 05 — Side Effects, Idempotency, and Human Approval

One operation can change external reality. Approval must gate it, an idempotency key must bound its retries, and an unprovable outcome must stay UNKNOWN — never flattened into success or failure. This lesson reuses the three `order-brief` workers as read-only preconditions and adds the project's first mutating step against a scripted, file-backed effect ledger. No model, API key, real network, or real payment service is involved.

## Read-Only Preconditions

For `ORD-1001`, the fixed queue `order-details`, `payment-status`, `delivery-status` runs exactly as in Lessons 03–04: bounded (two slots), once-only, store-integrated. Retrying reads is always free — the safe half of every retry boundary. When any read fails, the run stops before approval: no approval is requested, no effect is submitted, and the M4 status table applies.

## The Approval Gate

The effect payload is closed: `{operation:'cancel-and-refund', order_id:'ORD-1001', refund_amount_cents:4200, currency:'EUR'}`. Approval binds to `(operation, order_id, payload_digest)`; the digest is the SHA-256 of the canonical payload. A changed payload invalidates any prior approval. A rejected decision is terminal for the run — `FAILED` / `APPROVAL_REJECTED`, zero submissions, and an audit record of the rejection. Approval and rejection both append to the audit log.

## The Idempotent Effect and Its Ledger

The idempotency key is derived in code — `cancel-and-refund:ORD-1001` — never per attempt, never from model output. The scripted ledger is a JSON file at the state-directory root with atomic writes and once-per-key enforcement: a duplicate submission adopts the original recorded outcome and mutates nothing. An invalid payload records `EFFECT_REJECTED` once.

The write-ahead discipline extends M4: the run-state document records a `submit_marker` (key + digest) **before** the ledger is called, and the confirmed `effect` record after the ledger answers. The submit→confirm window is the only unsafe window in the system.

## UNKNOWN: When Reality Cannot Be Proven

A scripted crash control can fire inside the submit window: the ledger accepted the submission but the run died before recording it. On resume the runtime queries the ledger by key:

| Ledger state | Resolution |
|---|---|
| key present | adopt the original outcome → `SUCCEEDED`, `reconciled: true`, zero new submissions |
| key absent | re-submit once under the same key → `SUCCEEDED` |
| lookup unavailable | run terminates `UNKNOWN` — result line, exit `0`, state document `UNKNOWN`, never flattened |

`UNKNOWN` carries the idempotency key and `effect_status: EFFECT_UNPROVABLE`. No retry logic silently resolves it.

## The Naive Failure: Refiring the Effect

The teaching example in `typescript/test/naive-example.test.ts` and `python/tests/test_naive_example.py` seeds a submit-window crash, then retries naively — submitting again without consulting anything:

```text
submit-window crash: ledger accepted, run died before recording
naive retry:         submit again            → the key absorbs it (duplicate, one record)
corrected resume:    lookup by key           → adopt, reconciled, zero submissions
```

The demonstration proves both behaviors with instrumented counters: the naive path makes one extra submission attempt (which the key suppresses — in a real system without a ledger, this is the duplicate refund), while the corrected resume makes zero.

## Canonical Cases

Six paired offline cases:

| Case | Phases | Outcome |
|---|---|---|
| `approval-granted-effect-once` | 1 run | `SUCCEEDED`, one ledger record |
| `approval-rejected-no-effect` | 1 run | `FAILED`/`APPROVAL_REJECTED`, zero submissions |
| `retry-before-submit` | crash + resume | resume submits once → `SUCCEEDED` |
| `crash-submit-window-resolved` | crash + resume | resume adopts by key → `SUCCEEDED`, `reconciled: true` |
| `sink-unavailable-unknown` | crash + resume | resume terminates `UNKNOWN`, never flattened |
| `duplicate-key-suppressed` | run + fresh run | second run adopts, ledger unchanged |

Example crash-resume flow:

```bash
python -m boundrelay_m5 --case crash-submit-window-resolved --trace c1.jsonl --state-dir state   # exit 2
python -m boundrelay_m5 --case crash-submit-window-resolved --trace c2.jsonl --state-dir state --resume   # exit 0, reconciled
npx tsx src/cli.ts --case crash-submit-window-resolved --trace c1.jsonl --state-dir state
npx tsx src/cli.ts --case crash-submit-window-resolved --trace c2.jsonl --state-dir state --resume
```

## Audit and Trace

The audit log (`<state-dir>/audit.jsonl`) is append-only history: one record per approval decision and per effect attempt. The runtime appends but never reads it back for decisions. Traces gain the foundation-declared `approval.requested/granted/rejected` and `tool.requested/completed/failed` event types; payloads carry safe identifiers, digests, and the key — never ledger contents. The envelope stays at version `1.0`.

## Invariants and Verification

The twenty invariants (`M5-01`–`M5-20` in `invariants.yaml`) cover approval binding, key determinism, once-per-key, the UNKNOWN boundary, audit discipline, event privacy, M4 durability beneath M5, parity, and revision-bound evidence. The authority is `python scripts/verify_m5.py` (chaining M4→M0), publishing `.boundrelay/m5/verification-evidence.json` only for an unchanged HEAD; CI uploads `m5-verification-<revision>`.

## Limits

No real networks or payment services, approval services, transactional outboxes, message queues, distributed locks, model-driven effects, timeouts, Go, MCP, or framework mappings. The approver is a scripted fixture decision.

