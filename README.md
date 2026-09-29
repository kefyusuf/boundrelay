# BoundRelay

> Learn and build bounded, observable agent orchestration from first principles across TypeScript, Python, and Go.

## Project status

**Phase:** M1 bounded single-agent tool loop complete.

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
