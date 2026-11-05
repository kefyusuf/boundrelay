# Lab 2 — Handoff boundaries (M2 support-handoff)

**Invariant under attack:** the sender's intent stays separate from the receiver's minimum context; context loss and receiver unavailability reject the handoff without dispatch; low confidence falls back deterministically.

## Exercise 1 — M2-F1: context loss (matrix row `M2-F1`)

```bash
cd lessons/02-routing-handoff/typescript
npx tsx src/cli.ts --mode model --case handoff-context-loss --trace f1.jsonl
```

**Expected:** exit `0`, `status: FAILED`, `failure_code: HANDOFF_CONTEXT_INVALID`, `specialist_invoked: false`. The receiver rejects the handoff because the minimum context (`ticket_id + request_text`) is incomplete.

## Exercise 2 — M2-F2: unavailable receiver (matrix row `M2-F2`)

```bash
npx tsx src/cli.ts --mode model --case handoff-receiver-unavailable --trace f2.jsonl
```

**Expected:** exit `0`, `status: FAILED`, `failure_code: HANDOFF_RECEIVER_UNAVAILABLE`, zero dispatches. The router chose correctly, but the receiver's availability is a separate boundary.

## Exercise 3 — M2-F3: low-confidence fallback (matrix row `M2-F3`)

```bash
npx tsx src/cli.ts --mode model --case model-low-confidence-fallback --trace f3.jsonl
```

**Expected:** exit `0`, `status: SUCCEEDED`, `fallback_applied: true` — the fixed 0.80 confidence policy demoted the model's proposal to the deterministic general route. This row is *not* a failure: it is the policy working.

Inspect:

```bash
python tools/inspector.py --trace f3.jsonl
```

The timeline shows `model.completed` → `route.selected` (with `fallback_applied`) → `handoff.accepted`.

## Exercise 4 — prove the boundaries

```bash
python -m unittest tools.parity.test_m2_verification_safety -v
```

## Discussion

1. Context loss is detected by the *receiver*, not the router. Why does that division make the boundary enforceable?
2. Fallback silently changes the destination route. When is a silent demotion acceptable, and when must it be surfaced to the caller?
3. Sender intent (route + confidence) travels separately from receiver input (ticket + text). What leak does this prevent?
