# BoundRelay

> Learn and build bounded, observable agent orchestration from first principles across TypeScript, Python, and Go.

## Project status

**Phase:** M3 bounded fan-out/fan-in implemented; certify the checked-out revision with `python scripts/verify_m3.py`.

M3 adds three independent offline order-brief workers, sequential limit 1 and parallel limit 2, typed partial/all-failed outcomes, complete canonical fan-in and one deterministic synthesizer. Six paired cases demonstrate bounded overlap, out-of-order completion, declared failures and invalid output. Independent worker-body probes prove real overlap and once-only invocation; raw-first trace validation preserves failure evidence. M3 certification invokes M2 once, retaining the M2→M1→M0 chain.

M2 adds an offline support-router → deterministic specialist handoff in TypeScript and Python. Route decisions are validated before a fixed `0.80` confidence policy; sender intent remains separate from the receiver's minimum `ticket_id + request_text` context. Five canonical cases cover code/model routing, low-confidence fallback, context loss, and unavailable receivers. Success invokes exactly one receiver; rejection invokes none and never retries. M2 certification retains M1 as the lower-milestone authority.

M0 remains the deterministic-vs-model routing baseline. M1 adds an offline, deterministic, read-only single-agent tool loop for the canonical `order-investigation` scenario: a direct function-call baseline, a bounded model–tool–observation loop, two typed read-only tools, hard model-step/token budgets, fail-closed validation, explicit timeout/execution failures, strict JSONL traces, and TypeScript/Python behavioral parity.

The M1 certification gate runs the existing M0 authority first, then validates all eight M1 canonical cases in both languages. Passing evidence is bound to the exact Git revision and written under `.boundrelay/m1/`; GitHub Actions runs the same authority command on Node.js 24 and Python 3.14 and uploads `m1-verification-<revision>`.

## Verify M0 locally

Requirements: Node.js 24 and Python 3.14. From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install -e lessons/00-workflow-or-agent/python
npm ci --prefix lessons/00-workflow-or-agent/typescript
python scripts/verify_m0.py
```

The M0 gate runs contract tests, both language test suites, verification-safety tests, and seven parity cases. Because evidence is bound to `HEAD`, the certification gate requires a clean Git worktree. See [Lesson 00](lessons/00-workflow-or-agent/README.md) for the complete walkthrough.

## Verify M1 locally

Install both lessons because M1 intentionally keeps M0 as a regression authority:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install -e lessons/00-workflow-or-agent/python
python -m pip install -e lessons/01-bounded-tool-loop/python
npm ci --prefix lessons/00-workflow-or-agent/typescript
npm ci --prefix lessons/01-bounded-tool-loop/typescript
python scripts/verify_m1.py
```

The M1 gate clears previous M1 evidence, runs the M0 authority, runs M1 contracts and both language test suites, validates verifier safety, executes all eight canonical cases through both CLIs, and compares normalized results and traces. A passing run writes revision-bound evidence to `.boundrelay/m1/verification-evidence.json`.

M1 remains deliberately offline and read-only. It does not add real model providers, retries, mutating tools, persistence, approval/idempotency, Go parity, MCP/framework adapters, or a shared general-purpose runtime. See [Lesson 01](lessons/01-bounded-tool-loop/README.md).

## Verify M2 locally

After installing M0 and M1 as above, install Lesson 02:

```bash
python -m pip install -e lessons/02-routing-handoff/python
npm ci --prefix lessons/02-routing-handoff/typescript
python scripts/verify_m2.py
```

The gate requires a clean Git worktree, runs M1 (including M0), verifies both M2 implementations and five paired CLI cases, and publishes `.boundrelay/m2/verification-evidence.json` only if HEAD remains unchanged. GitHub Actions runs the same command and uploads `m2-verification-<revision>`. See [Lesson 02](lessons/02-routing-handoff/README.md) for setup, lifecycle, failure semantics, and exercises. M2 keeps receivers deterministic and read-only; real providers, retries, persistence, side effects, Go, parallelism, and framework adapters remain deferred.

## Verify M3 locally

After installing M0/M1/M2 as above, install Lesson 03:

```bash
python -m pip install -e lessons/03-parallel-fanout-fanin/python
npm ci --prefix lessons/03-parallel-fanout-fanin/typescript
python scripts/verify_m3.py
```

The authority runs both implementations, independent concurrency probes, offline guards, safety tests, six paired cases and twelve raw traces. It requires clean unchanged HEAD and matching lower-milestone proofs before publishing `.boundrelay/m3/verification-evidence.json`. CI runs the same authority on the exact candidate revision and uploads `m3-verification-<revision>`. See [Lesson 03](lessons/03-parallel-fanout-fanin/README.md) for execution, failure policy and exercises. This lesson remains finite and offline; real providers, dynamic topology, runtime deadlines/cancellation, persistence/recovery and external business writes remain deferred.

## Project identity

**BoundRelay** is the umbrella name. The initial repository slug is `boundrelay`. The name combines:

- **Bound:** explicit contracts, budgets, permissions, stop conditions, and failure boundaries;
- **Relay:** routing, delegation, handoffs, fan-out/fan-in, and cross-language coordination.

The initial repository remains one focused learning system. Names such as **BoundRelay Learn**, **BoundRelay Protocol**, **BoundRelay Runtime**, **BoundRelay CLI**, and **BoundRelay Inspector** are reserved as future product-family labels and will only be created when independent artifacts genuinely exist.

## The problem

Most agent tutorials optimize for the first successful demo. They rarely teach:

- when a deterministic workflow is better than an agent;
- what an orchestrator actually owns;
- how state, handoffs, retries, timeouts, budgets, approvals, and failure recovery interact;
- how to test nondeterministic systems through deterministic invariants;
- how the same orchestration concepts map across languages without becoming framework-specific.

This project teaches those boundaries explicitly.

## Core promise

Every lesson follows the same sequence:

1. Define the problem and success criteria.
2. Build the deterministic baseline first.
3. Introduce the smallest agentic mechanism that might help.
4. Run an intentionally naive implementation.
5. Inject a realistic failure.
6. Correct the design with explicit contracts and controls.
7. Verify observable invariants across supported languages.
8. Explain when the agentic version should not be used.

## Canonical source of truth

No programming language is canonical. The canonical artifacts are:

- the scenario specification;
- input and output schemas;
- observable event contracts;
- golden fixtures;
- failure cases;
- verification invariants.

Language implementations are expected to be idiomatic, not line-by-line translations.

## Initial language rollout

- **v0.1:** TypeScript and Python, lessons 00–05.
- **v0.2:** Go parity for the stable lessons.
- **v0.3:** Optional framework mappings and adapters.
- **v1.0:** Production track, complete fault-injection labs, and a trace inspector.

## What this project is not

- It is not another general-purpose agent framework.
- It is not a no-code automation platform.
- It is not a collection of provider-specific snippets.
- It does not treat an LLM response as proof that a workflow succeeded.
- It does not expose or require private chain-of-thought.
- It does not add multi-agent topology when named functions or a deterministic workflow are sufficient.

## Foundation documents

- [Foundation design](docs/design/2026-09-02-foundation-design.md)
- [Roadmap](ROADMAP.md)
- [Decision index](docs/decisions/README.md)
- [Turkish overview](README.tr.md)
