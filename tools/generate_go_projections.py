"""Generate the Go fixture projections from the M0/M3 YAML sources.

Go's standard library has no YAML parser, so the Go runtimes load the M0
(support-triage) and M3 (order-brief) fixtures from checked-in JSON
projections under fixtures/goprojections/<scenario>/: scenario.json (the
full scenario document including the attribution tables), workers.json (the
worker fixtures referenced by the scenario's cases, keyed by repo-relative
path), and attribution.json (the scenario's attribution block).

The generator refuses to run on top of uncommitted tracked changes and
prints a review-visible unified diff against the previous projections.

Standalone tool: plain Python + PyYAML, no lesson imports.
"""
from __future__ import annotations

import argparse
import difflib
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
GO_SCENARIOS = ("support-triage", "order-brief")
PROJECTION_ROOT = ROOT / "fixtures/goprojections"


class ToolingError(RuntimeError):
    """Missing sources or an unsafe worktree: the generator fails closed."""


def _git_status() -> str:
    completed = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, check=True,
        capture_output=True, text=True)
    return completed.stdout


def _assert_clean_worktree() -> None:
    """Refuse generation when uncommitted tracked changes could silently
    drift the projections away from the reviewed sources. Untracked files
    (including not-yet-committed projections) are tolerated."""
    tracked = [line for line in _git_status().splitlines()
               if line.strip() and not line.startswith("??")]
    if tracked:
        raise ToolingError(
            "Go projection generation requires committed tracked sources; "
            "the worktree carries uncommitted tracked changes:\n"
            + "\n".join(tracked))


def scenario_document(scenario_id: str) -> dict:
    path = ROOT / f"fixtures/scenarios/{scenario_id}.yaml"
    if not path.exists():
        raise ToolingError(f"Missing scenario fixture: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("cases"), list):
        raise ToolingError(
            f"{scenario_id}: scenario document must be an object with cases")
    if not isinstance(document.get("attribution"), dict):
        raise ToolingError(
            f"{scenario_id}: scenario document must carry an attribution table")
    return document


def worker_fixtures(document: dict) -> dict[str, dict]:
    """Parse the worker fixtures referenced by the scenario's cases, keyed
    by their repo-relative fixture path in first-reference order."""
    workers: dict[str, dict] = {}
    for case in document["cases"]:
        ref = case.get("worker_fixture") if isinstance(case, dict) else None
        if not ref:
            continue
        path = ROOT / ref
        if not path.exists():
            raise ToolingError(f"Missing worker fixture: {path}")
        if ref not in workers:
            workers[ref] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return workers


def projection_payloads(scenario_id: str) -> dict[str, dict]:
    document = scenario_document(scenario_id)
    return {"scenario.json": document,
            "workers.json": worker_fixtures(document),
            "attribution.json": document["attribution"]}


def serialize(payload: dict) -> str:
    return json.dumps(payload, indent=2) + "\n"


def generate_scenario(scenario_id: str) -> str:
    """Write one scenario's projections; report unified diffs against the
    previous projection contents so every change is review-visible."""
    report: list[str] = []
    for name, payload in projection_payloads(scenario_id).items():
        path = PROJECTION_ROOT / scenario_id / name
        relpath = path.relative_to(ROOT).as_posix()
        text = serialize(payload)
        if path.exists():
            previous = path.read_text(encoding="utf-8")
            if previous == text:
                report.append(f"No changes: {relpath}")
                continue
            report.append("".join(difflib.unified_diff(
                previous.splitlines(True), text.splitlines(True),
                fromfile=f"{relpath} (previous)",
                tofile=f"{relpath} (regenerated)")))
        else:
            report.append(f"Projection written (new): {relpath}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return "\n".join(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true",
                        help="generate projections for every Go scenario")
    parser.add_argument("--scenario", action="append", default=[],
                        help="scenario id (repeatable)")
    options = parser.parse_args(argv)
    try:
        selected = list(GO_SCENARIOS) if options.all else options.scenario
        if not selected:
            parser.error("one of --all or --scenario is required")
        unknown = [name for name in selected if name not in GO_SCENARIOS]
        if unknown:
            raise ToolingError(
                f"Unknown Go scenario(s) {unknown}; supported: {list(GO_SCENARIOS)}")
        _assert_clean_worktree()
        for scenario_id in selected:
            print(f"== {scenario_id} ==")
            print(generate_scenario(scenario_id))
    except ToolingError as error:
        print(f"tooling error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
