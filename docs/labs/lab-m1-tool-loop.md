# Lab 1 — Tool-loop failures (M1 order-investigation)

**Invariant under attack:** the bounded model–tool–observation loop fails closed on every declared tool failure class, with exact counters and no silent retries.

All exercises use the agent mode with the four canonical failure cases (matrix rows `M1-F1`…`M1-F4`).

## Exercises

Each exercise maps to its matrix row: `M1-F1`, `M1-F2`, `M1-F3`, `M1-F4`.

Run each case and compare its counters against the expected response:

```bash
cd lessons/01-bounded-tool-loop/typescript
npx tsx src/cli.ts --mode agent --case agent-unknown-tool --trace f1.jsonl          # UNKNOWN_TOOL, tool_invocations 0
npx tsx src/cli.ts --mode agent --case agent-invalid-arguments --trace f2.jsonl     # INVALID_TOOL_ARGUMENTS, tool_invocations 0
npx tsx src/cli.ts --mode agent --case agent-tool-timeout --trace f3.jsonl          # TOOL_TIMEOUT, tool_invocations 1
npx tsx src/cli.ts --mode agent --case agent-tool-failure --trace f4.jsonl          # TOOL_EXECUTION_FAILED, tool_invocations 1
```

**Expected for all:** exit `0`, `status: FAILED`, one model step consumed, no retry, the failure code matching the row. The difference between the first two (tool never invoked) and the last two (tool invoked once, then failed) is the teaching point: argument validation happens *before* dispatch.

Inspect one trace:

```bash
python tools/inspector.py --trace f3.jsonl
```

The timeline shows `tool.requested` → `tool.failed` → `run.failed` with the failure code — the loop stops on the first failure.

## Exercise 2 — budget exhaustion (bonus, outside the matrix)

```bash
npx tsx src/cli.ts --mode agent --case agent-step-budget --trace b1.jsonl   # STEP_BUDGET_EXCEEDED after 2 model steps
npx tsx src/cli.ts --mode agent --case agent-token-budget --trace b2.jsonl  # TOKEN_BUDGET_EXCEEDED after 75 tokens
```

## Exercise 3 — prove the counters

```bash
python -m unittest tools.parity.test_m1_verification_safety -v
```

## Discussion

1. Unknown tool and invalid arguments fail *before* the tool runs; timeout and execution failure fail *after*. Why does the loop treat these differently (invocation counts 0 vs 1)?
2. No failure retries. What would a retry need to be safe here, and which milestone's machinery would it need? (Hint: durable state.)
3. Budgets are hard limits, not warnings. What did the loop abandon mid-flight when the budget hit, and who cleans that up?
