# BoundRelay

> Learn and build bounded, observable agent orchestration from first principles across TypeScript, Python, and Go.

## Project status

**Phase:** M0 in implementation.

The first vertical slice now has canonical scenarios and contracts, TypeScript and Python implementations, offline scripted decisions, JSONL traces, and a cross-language parity gate. M0 remains incomplete until the exact candidate revision passes both local verification and GitHub Actions.

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

The gate runs contract tests, both language test suites, seven parity cases, and writes ignored evidence under `.boundrelay/m0/`. See [Lesson 00](lessons/00-workflow-or-agent/README.md) for the complete walkthrough.

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
