# Lesson 02 — Routing and typed handoff

## Problem

A router can classify a support ticket correctly while transferring unusable context to the wrong receiver. A route decision names a destination; a handoff is the separately validated transfer of responsibility. This lesson makes that boundary observable in offline TypeScript and Python implementations.

## Success criteria

- Validate every route decision against the existing M0 schema before applying policy.
- Preserve proposed route when confidence is at least `0.80`; otherwise select `general`.
- Transfer exactly `ticket_id` and `request_text` to one deterministic receiver.
- Reject lost context or an unavailable receiver before invocation, without retry.
- Produce equivalent normalized results and JSONL traces in both languages.
- Keep M1 green and bind certification evidence to the tested Git revision.

## Deterministic baseline

The code router matches billing keywords first (`charged`, `charge`, `invoice`, `payment`, `refund`, `billed`), then technical keywords (`error`, `crash`, `cannot log in`, `can't log in`, `bug`, `broken`), otherwise `general`. Its confidence is `1.0` and it emits no model events.

The fixed mapping is billing → billing-specialist, technical → technical-specialist, general → general-specialist. Receivers are named async functions with no model, tool, network, persistence, or side effects. A **named specialist != autonomous agent**.

## Reason to introduce model judgment

A request such as “The verification screen keeps rejecting the code and I cannot get in” does not match this keyword baseline. A scripted model fixture proposes `technical / 0.92`. This demonstrates the narrow judgment boundary without an API key or nondeterministic provider.

A **confidence proposal != fallback policy**. Both routing modes feed the same deterministic policy and handoff validation. At `0.80`, the proposed route is preserved; at `0.79`, the receiver is general-specialist. The low-confidence canonical case proposes billing at `0.54`, so its sender intent still records billing while its selected receiver is general-specialist.

## Naive implementation

This shortcut omits the responsibility-transfer boundary:

```typescript
const decision = await model.nextDecision({caseId, request});
await receivers.resolve(decision.route).handle({request_text: request});
```

It trusts an unvalidated decision, skips confidence policy, loses the ticket identifier, assumes receiver availability, and cannot distinguish a proposed transfer from an accepted one. A **route decision != handoff authorization**.

## Failure injection

Exactly five canonical cases are shared by both implementations:

| Case | Mode | Proposed / confidence | Selected receiver | Outcome |
|---|---|---|---|---|
| code-billing-handoff | code | billing / 1.00 | billing-specialist | SUCCEEDED |
| model-technical-handoff | model | technical / 0.92 | technical-specialist | SUCCEEDED |
| model-low-confidence-fallback | model | billing / 0.54 | general-specialist | SUCCEEDED |
| handoff-context-loss | model | billing / 0.93 | billing-specialist | HANDOFF_CONTEXT_INVALID |
| handoff-receiver-unavailable | code | billing / 1.00 | billing-specialist | HANDOFF_RECEIVER_UNAVAILABLE |

The context-loss fixture omits only `receiver_input.request_text`. The unavailable-receiver fixture removes only billing-specialist from that case's receiver directory. Successful cases inherit neither injection. An invalid model route is tested as a pre-handoff boundary, rather than a sixth milestone case.

## Corrected implementation

The runtime obtains and validates a route, applies the fixed policy, constructs a candidate envelope, and emits `handoff.requested`. It then validates the full envelope, resolves receiver availability, emits `handoff.accepted`, and invokes the receiver exactly once with only its validated input.

```json
{
  "schema_version": "1.0",
  "handoff_id": "handoff-generated",
  "sender": "support-router",
  "receiver": "general-specialist",
  "sender_intent": {"route": "billing", "confidence": 0.54, "policy_outcome": "fallback"},
  "receiver_input": {"ticket_id": "TCK-1003", "request_text": "Something about my invoice looks wrong but I am not sure what happened."}
}
```

A **sender intent != receiver input**. Receivers do not obtain the model decision, sender intent, prompts, or full orchestration state. Every object boundary rejects extra fields.

Domain failures produce one JSON result and exit `0`. Invalid routes emit `route.rejected` before any handoff or receiver resolution. Rejected handoffs emit requested → rejected → run.failed and invoke zero receivers. Configuration/provider errors and unexpected receiver exceptions propagate to CLI diagnostics and exit `2`; they do not invent another handoff failure code or trigger a retry. A tooling exception does not produce a certified domain result/trace.

## Verification evidence

Requirements: Node.js 24 or later and Python 3.14 or later. From the repository root, create and activate `.venv`, then install:

```bash
python -m pip install -r requirements-dev.txt
python -m pip install -e lessons/00-workflow-or-agent/python
python -m pip install -e lessons/01-bounded-tool-loop/python
python -m pip install -e lessons/02-routing-handoff/python
npm ci --prefix lessons/00-workflow-or-agent/typescript
npm ci --prefix lessons/01-bounded-tool-loop/typescript
npm ci --prefix lessons/02-routing-handoff/typescript
python scripts/verify_m2.py
```

On PowerShell, activate with `.venv\Scripts\Activate.ps1`; on POSIX shells, use `source .venv/bin/activate`. Certification requires a clean Git worktree. The authority clears stale M2 evidence, captures the candidate revision, invokes M1 (which invokes M0), runs contracts, both language suites, verifier-safety tests, and all five paired CLI executions. It checks schemas, lifecycle order, binding of case/mode/run/trace, minimum context, confidence policy, rejection semantics, and normalized parity. Publication rechecks clean worktree and unchanged HEAD.

Evidence is generated under `.boundrelay/m2/verification-evidence.json`; ten traces live under `.boundrelay/m2/traces/`. These ignored files are never committed. CI executes the same command and retains `m2-verification-<exact-head-sha>` for 14 days. Unit tests use recording receivers to prove actual invocation count and exact input; parity alone cannot prove a function was called.

Example individual runs:

```bash
npm --prefix lessons/02-routing-handoff/typescript run run -- --mode model --case model-low-confidence-fallback --trace .boundrelay/fallback.ts.jsonl
python -m boundrelay_m2 --mode model --case model-low-confidence-fallback --trace .boundrelay/fallback.py.jsonl
```

With `npm --prefix`, a relative trace path is relative to the lesson package. Supply an absolute path to place both outputs in the same directory. The certification command handles this automatically.

## Trade-offs

The small, scenario-specific envelope makes failure boundaries inspectable without designing a universal agent protocol. Duplicated lesson-local implementations keep lessons independently understandable; schemas, fixtures, and parity protect their shared behavior. Generated IDs, timestamps, source labels, and trace paths are ignored only during comparison. Receiver identity, input, intent, decisions, and failure codes remain compared.

## When not to use this pattern

If one named function can handle a known request with all required input, call it directly. This lesson does not justify model-backed receivers or a general-purpose multi-agent runtime. Retries, persistent recovery, side effects, approvals, parallelism, Go, real providers, MCP, and framework adapters belong to later accepted milestones.

## Exercises

1. Inject confidence `0.80`, then `0.79`; inspect proposed route, selected route, and sender intent.
2. Add an extra receiver-input field in a unit test and prove validation rejects it before receiver resolution.
3. Return an unknown route from an injected provider and prove no handoff event is emitted.
4. Inject a receiver exception and prove one invocation, no retry, and CLI exit `2`.
5. Mutate a recorded trace's handoff ID or selected receiver and prove the verifier detects the mismatch before normalization.
