"""M6 regression evaluator: run canonical cases through both language CLIs,
normalize the evidence, and compare it against the recorded goldens.

Fail-closed: a missing golden, a failed language run, a cross-language
divergence, or a golden divergence is a tooling error (exit 2). Goldens are
recorded only through --regenerate, which refuses to run on top of uncommitted
tracked changes and prints a review-visible diff.

Standalone tool: plain Python + PyYAML, no lesson imports.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ("support-triage", "order-investigation", "support-handoff",
             "order-brief", "order-brief-recovery", "order-closure")
GOLDEN_ROOT = ROOT / "fixtures/goldens"
TS_ROOTS = {
    "support-triage": "lessons/00-workflow-or-agent/typescript",
    "order-investigation": "lessons/01-bounded-tool-loop/typescript",
    "support-handoff": "lessons/02-routing-handoff/typescript",
    "order-brief": "lessons/03-parallel-fanout-fanin/typescript",
    "order-brief-recovery": "lessons/04-durable-state-recovery/typescript",
    "order-closure": "lessons/05-side-effects-approval/typescript",
}
PY_MODULES = {
    "support-triage": "boundrelay_m0", "order-investigation": "boundrelay_m1",
    "support-handoff": "boundrelay_m2", "order-brief": "boundrelay_m3",
    "order-brief-recovery": "boundrelay_m4", "order-closure": "boundrelay_m5",
}
PY_SRC = [ROOT / f"lessons/{d}/python/src" for d in (
    "00-workflow-or-agent", "01-bounded-tool-loop", "02-routing-handoff",
    "03-parallel-fanout-fanin", "04-durable-state-recovery",
    "05-side-effects-approval")]


class ToolingError(RuntimeError):
    """Missing or divergent evidence: the evaluator fails closed."""


def scenario_cases(scenario_id: str) -> list[dict[str, str | None]]:
    """Discover the canonical case keys; M0 keys are '<case_id>@<mode>'."""
    path = ROOT / f"fixtures/scenarios/{scenario_id}.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    specs: list[dict[str, str | None]] = []
    if scenario_id == "support-triage":
        for case in document["cases"]:
            if "expected_route" in case:
                for mode in ("deterministic", "model"):
                    specs.append({"key": f"{case['id']}@{mode}",
                                  "case_id": case["id"], "mode": mode})
            elif case.get("expected_failure_code") == "INVALID_ROUTE_DECISION":
                specs.append({"key": f"{case['id']}@model",
                              "case_id": case["id"], "mode": "model"})
            else:
                raise ToolingError(f"Unsupported M0 case expectation: {case}")
        if len(specs) != 7:
            raise ToolingError(f"M0 must expose seven canonical runs, got {len(specs)}")
        return specs
    key_field = "case_id" if scenario_id in ("order-brief", "order-brief-recovery",
                                             "order-closure") else "id"
    mode_field = {"order-investigation": "mode", "support-handoff": "router_mode",
                  "order-brief": "execution_mode"}.get(scenario_id)
    for case in document["cases"]:
        specs.append({"key": case[key_field], "case_id": case[key_field],
                      "mode": case.get(mode_field) if mode_field else None})
    return specs


def _spawn(command: list[str]) -> tuple[int, str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    sources = os.pathsep.join(str(path) for path in PY_SRC)
    env["PYTHONPATH"] = sources + (os.pathsep + existing if existing else "")
    process = subprocess.run(command, cwd=str(ROOT), env=env, text=True, capture_output=True)
    return process.returncode, process.stdout, process.stderr


def _git_status() -> str:
    return subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=str(ROOT), text=True, capture_output=True).stdout


def _command(scenario_id: str, language: str, args: list[str]) -> list[str]:
    if language == "python":
        return [sys.executable, "-m", PY_MODULES[scenario_id], *args]
    return [shutil.which("npm") or "npm", "--silent",
            "--prefix", str(ROOT / TS_ROOTS[scenario_id]), "run", "run", "--", *args]


def _cli_result(code: int, stdout: str, stderr: str, label: str) -> dict:
    if code != 0:
        raise ToolingError(f"{label} failed (exit {code}): {stderr.strip()[:400]}")
    lines = [line for line in stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ToolingError(f"{label} must print exactly one JSON result line")
    value = json.loads(lines[0])
    if not isinstance(value, dict):
        raise ToolingError(f"{label} result must be a JSON object")
    return value


def _read_trace(path: Path, label: str) -> list[dict]:
    if not path.exists():
        raise ToolingError(f"{label}: trace file missing: {path}")
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ToolingError(f"{label}: trace records must be objects")
        events.append(event)
    return events


M4_PHASES = {
    "parallel-clean-complete": (("fresh", False),),
    "parallel-crash-resume": (("fresh", True), ("resume", False)),
    "parallel-crash-resume-partial": (("fresh", True), ("resume", False)),
    "parallel-cancel-resume": (("fresh", False), ("resume", False)),
    "parallel-replay-from-checkpoint": (("fresh", False), ("replay", False)),
    "parallel-corrupt-state": (("fresh", False), ("corrupt-resume", False)),
}
M5_PHASES = {
    "approval-granted-effect-once": (("fresh", False),),
    "approval-rejected-no-effect": (("fresh", False),),
    "retry-before-submit": (("fresh", True), ("resume", False)),
    "crash-submit-window-resolved": (("fresh", True), ("resume", False)),
    "sink-unavailable-unknown": (("fresh", True), ("resume", False)),
    "duplicate-key-suppressed": (("fresh", False), ("duplicate", False)),
}
PHASES = {"order-brief-recovery": M4_PHASES, "order-closure": M5_PHASES}


def _phased_language_flow(scenario_id: str, case_key: str, workdir: Path,
                          language: str) -> dict:
    state_dir = workdir / f"{case_key}.{language}.state"
    events: list[dict] = []
    result: dict | None = None
    run_id: str | None = None
    for kind, crash in PHASES[scenario_id][case_key]:
        trace = workdir / f"{case_key}.{language}.{kind}.jsonl"
        args = ["--case", case_key, "--trace", str(trace), "--state-dir", str(state_dir)]
        if kind == "resume":
            args.append("--resume")
        if kind == "replay":
            args += ["--replay-from", str(state_dir / run_id / "checkpoints" / "step-1.json")]
        label = f"{language} CLI {kind} phase for {scenario_id}/{case_key}"
        if kind == "corrupt-resume":
            _corrupt_resume_probe(scenario_id, case_key, workdir, language, state_dir)
            continue
        code, stdout, stderr = _spawn(_command(scenario_id, language, args))
        if crash:
            if code != 2 or stdout.strip():
                raise ToolingError(f"{label} must exit 2 without a result line: {stderr.strip()[:200]}")
        else:
            result = _cli_result(code, stdout, stderr, label)
            run_id = result.get("run_id")
        if trace.exists():
            events += _read_trace(trace, label)
    if result is None:
        raise ToolingError(f"{scenario_id}/{case_key}: no phase produced a result")
    return {"result": result, "events": events}


def _corrupt_resume_probe(scenario_id: str, case_key: str, workdir: Path,
                          language: str, state_dir: Path) -> None:
    tampered = workdir / f"{case_key}.{language}.tampered"
    shutil.copytree(state_dir, tampered)
    state_path = next((entry / "state.json" for entry in sorted(tampered.iterdir())
                       if (entry / "state.json").is_file()), None)
    if state_path is None:
        raise ToolingError(f"{scenario_id}/{case_key}: no state document to tamper")
    document = json.loads(state_path.read_text(encoding="utf-8"))
    document["steps"][1]["output"]["payment_status"] = "UNPAID"
    state_path.write_text(json.dumps(document), encoding="utf-8")
    trace = workdir / f"{case_key}.{language}.corrupt-resume.jsonl"
    args = ["--case", case_key, "--trace", str(trace), "--state-dir", str(tampered), "--resume"]
    label = f"{language} CLI corrupt-resume phase for {scenario_id}/{case_key}"
    code, stdout, stderr = _spawn(_command(scenario_id, language, args))
    if code != 2 or stdout.strip():
        raise ToolingError(f"{label} must exit 2 without a result line: {stderr.strip()[:200]}")


def _run_language_flow(scenario_id: str, spec: dict, workdir: Path,
                       language: str) -> dict:
    label = f"{language} CLI for {scenario_id}/{spec['key']}"
    if scenario_id in PHASES:
        return _phased_language_flow(scenario_id, spec["key"], workdir, language)
    trace = workdir / f"{spec['key']}.{language}.jsonl"
    args = ["--case", str(spec["case_id"]), "--trace", str(trace)]
    if spec["mode"] is not None:
        args = ["--mode", str(spec["mode"]), *args]
    code, stdout, stderr = _spawn(_command(scenario_id, language, args))
    result = _cli_result(code, stdout, stderr, label)
    return {"result": result, "events": _read_trace(trace, label)}


def run_flow(scenario_id: str, spec: dict, workdir: Path) -> dict:
    python_flow = _run_language_flow(scenario_id, spec, workdir, "python")
    typescript_flow = _run_language_flow(scenario_id, spec, workdir, "typescript")
    return {"result": python_flow["result"], "events": python_flow["events"],
            "ts_result": typescript_flow["result"], "ts_events": typescript_flow["events"]}


def project_result(result: dict) -> dict:
    """The gate-style business projection: everything but volatile fields."""
    return {key: value for key, value in result.items()
            if key not in ("run_id", "trace_path", "state_dir")}


def event_sequence(events: list[dict]) -> list[dict]:
    """Ordered [{type, step_name}...]; union across phases (crash phases
    contribute their prefix and carry no terminal event)."""
    sequence = []
    for event in events:
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        sequence.append({"type": event["type"],
                         "step_name": data.get("step_name") or data.get("step")})
    return sequence


def flow_evidence(flow: dict) -> dict:
    """Cross-language parity, then the normalized golden evidence."""
    projections = (project_result(flow["result"]), project_result(flow["ts_result"]))
    if projections[0] != projections[1]:
        raise ToolingError(
            f"typescript and python result projections diverge: "
            f"{json.dumps(projections[0])} vs {json.dumps(projections[1])}")
    sequences = (event_sequence(flow["events"]), event_sequence(flow["ts_events"]))
    if sequences[0] != sequences[1]:
        raise ToolingError("typescript and python event sequences diverge: "
                           f"{json.dumps(sequences[0])} vs {json.dumps(sequences[1])}")
    if flow["result"].get("attribution") != flow["ts_result"].get("attribution"):
        raise ToolingError("typescript and python attributions diverge")
    return {"result_projection": projections[0],
            "event_sequence": sequences[0],
            "attribution": flow["result"]["attribution"]}


def compare_with_golden(scenario_id: str, case_key: str, actual: dict) -> dict:
    path = GOLDEN_ROOT / scenario_id / f"{case_key}.json"
    if not path.exists():
        raise ToolingError(f"Missing golden for {scenario_id}/{case_key}: {path}")
    golden = json.loads(path.read_text(encoding="utf-8"))
    for field in ("result_projection", "event_sequence", "attribution"):
        if golden.get(field) != actual[field]:
            raise ToolingError(
                f"Golden divergence for {scenario_id}/{case_key} in {field}: "
                f"{json.dumps(actual[field])[:300]} vs {json.dumps(golden.get(field))[:300]}")
    return golden


def _assert_clean_worktree() -> None:
    status = _git_status()
    if status.strip():
        raise ToolingError(
            "Golden regeneration requires a clean worktree "
            "(no uncommitted tracked changes):\n" + status)


def regenerate(scenario_id: str, case_key: str) -> str:
    """Record the current behavior as the golden (TS projection canonical;
    refuses to record diverging languages)."""
    _assert_clean_worktree()
    spec = next((entry for entry in scenario_cases(scenario_id)
                 if entry["key"] == case_key), None)
    if spec is None:
        raise ToolingError(f"Unknown case key {case_key} for {scenario_id}")
    with tempfile.TemporaryDirectory() as directory:
        flow = run_flow(scenario_id, spec, Path(directory))
    actual = flow_evidence(flow)
    golden = {"scenario_id": scenario_id, "case_key": case_key,
              "languages": ["typescript", "python"], **actual}
    path = GOLDEN_ROOT / scenario_id / f"{case_key}.json"
    diff = ""
    existed = path.exists()
    if existed:
        previous = path.read_text(encoding="utf-8")
        diff = "".join(difflib.unified_diff(
            previous.splitlines(True),
            (json.dumps(golden, indent=2) + "\n").splitlines(True),
            fromfile=f"golden/{scenario_id}/{case_key} (previous)",
            tofile=f"golden/{scenario_id}/{case_key} (regenerated)"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(golden, indent=2) + "\n", encoding="utf-8")
    if diff:
        return diff
    return f"No changes: {scenario_id}/{case_key} golden matches current behavior" if existed \
        else f"Golden written (new): {scenario_id}/{case_key}"


def evaluate(scenarios: list[str] | None = None, report_path: Path | None = None,
             only_case: str | None = None) -> dict:
    selected = [name for name in SCENARIOS
                if scenarios is None or name in scenarios]
    records = []
    for scenario_id in selected:
        for spec in scenario_cases(scenario_id):
            if only_case is not None and spec["key"] != only_case:
                continue
            record: dict = {"scenario_id": scenario_id, "case_key": spec["key"]}
            try:
                with tempfile.TemporaryDirectory() as directory:
                    flow = run_flow(scenario_id, spec, Path(directory))
                compare_with_golden(scenario_id, spec["key"], flow_evidence(flow))
                record.update({"status": "PASS", "languages": ["typescript", "python"]})
            except ToolingError as error:
                record.update({"status": "FAIL", "error": str(error)})
            records.append(record)
    totals = {"passed": sum(1 for record in records if record["status"] == "PASS"),
              "failed": sum(1 for record in records if record["status"] == "FAIL")}
    report = {"schema_version": "1.0",
              "generated_at": datetime.now(timezone.utc).isoformat(
                  timespec="seconds").replace("+00:00", "Z"),
              "scope": selected, "cases": records, "totals": totals}
    if report_path is not None:
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="evaluate all 38 canonical cases")
    parser.add_argument("--scenario", action="append", default=[],
                        help="limit the scope (repeatable)")
    parser.add_argument("--case", help="single case key (requires exactly one --scenario)")
    parser.add_argument("--regenerate", nargs=2, metavar=("SCENARIO", "CASE_KEY"),
                        help="record a golden for the case from current behavior")
    parser.add_argument("--report", type=Path, help="write evaluation-report.json here")
    options = parser.parse_args(argv)
    try:
        if options.regenerate:
            diff = regenerate(options.regenerate[0], options.regenerate[1])
            print(diff if diff else
                  f"Golden written (new): {options.regenerate[0]}/{options.regenerate[1]}")
            return 0
        if not options.all and not options.scenario:
            parser.error("one of --all, --scenario or --regenerate is required")
        if options.case and len(options.scenario) != 1:
            raise ToolingError("--case requires exactly one --scenario")
        report = evaluate(options.scenario or list(SCENARIOS),
                          report_path=options.report, only_case=options.case)
    except ToolingError as error:
        print(f"tooling error: {error}", file=sys.stderr)
        return 2
    print(f"evaluated {report['totals']['passed'] + report['totals']['failed']} cases: "
          f"{report['totals']['passed']} PASS, {report['totals']['failed']} FAIL")
    return 0 if report["totals"]["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

