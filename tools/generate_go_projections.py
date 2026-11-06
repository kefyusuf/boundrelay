"""Generate the Go fixture projections from the M0/M3/M1/M2 YAML sources.

Go's standard library has no YAML parser, so the Go runtimes load the M0
(support-triage), M3 (order-brief), M1 (order-investigation), and M2
(support-handoff) fixtures from checked-in JSON projections under
fixtures/goprojections/<scenario>/: scenario.json (the full scenario document
including the attribution tables), attribution.json (the scenario's
attribution block), plus per-scenario scripts — workers.json (the M0/M3
worker fixtures referenced by the scenario's cases, keyed by repo-relative
path), fake-model.json/fake-tools.json for M1 (the scripted fake-model turns
the M1 provider replays, exactly the values its TS/Python consumers extract
from each entry's `return`, and the orders/shipments data behind the fake
tool registry), or fake-model.json/failures.json for M2 (the scripted route
decisions exactly as the TS/Py ScriptedRouteProvider replays them — each
decision's `return` value — and the handoff failure fixtures behind the
receivers' availability and context validation).

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
GO_SCENARIOS = ("support-triage", "order-brief", "order-investigation",
                "support-handoff")
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


def fake_model_turns(scenario_id: str) -> dict:
    """Project the scripted fake-model fixture into the exact turn values its
    consumers replay: each trajectory entry's `return` value, keyed by case
    id (the ScriptedModelProvider contract)."""
    path = ROOT / f"fixtures/fake-model/{scenario_id}.yaml"
    if not path.exists():
        raise ToolingError(f"Missing fake-model fixture: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if (not isinstance(document, dict) or document.get("schema_version") != "1.0"
            or document.get("scenario_id") != scenario_id
            or not isinstance(document.get("trajectories"), dict)):
        raise ToolingError(
            f"{scenario_id}: fake-model document must be a 1.0 {scenario_id} "
            "document carrying trajectories")
    turns: dict[str, list] = {}
    for case_id, entries in document["trajectories"].items():
        if not isinstance(entries, list) or not entries:
            raise ToolingError(
                f"{scenario_id}: trajectory {case_id} must be a non-empty array")
        projected = []
        for entry in entries:
            if not isinstance(entry, dict) or "return" not in entry:
                raise ToolingError(
                    f"{scenario_id}: trajectory {case_id} entries must carry "
                    "return values")
            projected.append(entry["return"])
        turns[case_id] = projected
    return {"schema_version": document["schema_version"],
            "scenario_id": document["scenario_id"],
            "trajectories": turns}


def fake_route_decisions(scenario_id: str) -> dict:
    """Project the scripted fake-model fixture into the exact decision values
    its consumers replay: each `decisions` entry's `return` value, keyed by
    case id (the M2 ScriptedRouteProvider contract)."""
    path = ROOT / f"fixtures/fake-model/{scenario_id}.yaml"
    if not path.exists():
        raise ToolingError(f"Missing fake-model fixture: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if (not isinstance(document, dict) or document.get("schema_version") != "1.0"
            or document.get("scenario_id") != scenario_id
            or not isinstance(document.get("decisions"), dict)):
        raise ToolingError(
            f"{scenario_id}: fake-model document must be a 1.0 {scenario_id} "
            "document carrying decisions")
    decisions: dict[str, object] = {}
    for case_id, entry in document["decisions"].items():
        if not isinstance(entry, dict) or set(entry) != {"return"}:
            raise ToolingError(
                f"{scenario_id}: decision {case_id} must contain exactly return")
        decisions[case_id] = entry["return"]
    return {"schema_version": document["schema_version"],
            "scenario_id": document["scenario_id"],
            "decisions": decisions}


def handoff_failure_fixtures(scenario_id: str) -> dict:
    """Project the handoff failure fixtures (the scripted context-loss and
    receiver-unavailability operators behind the M2 receivers) verbatim."""
    path = ROOT / f"fixtures/failures/{scenario_id}.yaml"
    if not path.exists():
        raise ToolingError(f"Missing failures fixture: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if (not isinstance(document, dict) or document.get("schema_version") != "1.0"
            or document.get("scenario_id") != scenario_id
            or not isinstance(document.get("failures"), dict)):
        raise ToolingError(
            f"{scenario_id}: failures document must be a 1.0 {scenario_id} "
            "document carrying failures")
    for failure_id, entry in document["failures"].items():
        if not isinstance(entry, dict) or not entry:
            raise ToolingError(
                f"{scenario_id}: failure {failure_id} must be a non-empty object")
    return document


def fake_tool_fixtures(scenario_id: str) -> dict:
    """Project the fake-tool fixture (orders/shipments behind the M1 fake
    tool registry) as consumed: schema header plus the orders/shipments
    records, verbatim."""
    path = ROOT / f"fixtures/fake-tools/{scenario_id}.yaml"
    if not path.exists():
        raise ToolingError(f"Missing fake-tools fixture: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if (not isinstance(document, dict) or document.get("schema_version") != "1.0"
            or document.get("scenario_id") != scenario_id
            or not isinstance(document.get("orders"), dict)
            or not isinstance(document.get("shipments"), dict)):
        raise ToolingError(
            f"{scenario_id}: fake-tools document must be a 1.0 {scenario_id} "
            "document defining orders and shipments")
    for label, records in (("order", document["orders"]),
                           ("shipment", document["shipments"])):
        for entry_id, entry in records.items():
            if not isinstance(entry, dict):
                raise ToolingError(
                    f"{scenario_id}: {label} {entry_id} must be an object")
    return document


def projection_payloads(scenario_id: str) -> dict[str, dict]:
    document = scenario_document(scenario_id)
    if scenario_id == "order-investigation":
        return {"scenario.json": document,
                "fake-model.json": fake_model_turns(scenario_id),
                "fake-tools.json": fake_tool_fixtures(scenario_id),
                "attribution.json": document["attribution"]}
    if scenario_id == "support-handoff":
        return {"scenario.json": document,
                "fake-model.json": fake_route_decisions(scenario_id),
                "failures.json": handoff_failure_fixtures(scenario_id),
                "attribution.json": document["attribution"]}
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
