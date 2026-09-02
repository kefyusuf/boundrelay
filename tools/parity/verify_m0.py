from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Mapping

from jsonschema import Draft202012Validator, FormatChecker
import yaml

from tools.parity.normalize import normalize_result, normalized_trace, read_jsonl

ROOT = Path(__file__).resolve().parents[2]
SCENARIO_PATH = ROOT / "fixtures/scenarios/support-triage.yaml"
EVENT_SCHEMA_PATH = ROOT / "contracts/events/run-event.schema.json"
RESULT_SCHEMA_PATH = ROOT / "contracts/results/run-result.schema.json"
TS_ROOT = ROOT / "lessons/00-workflow-or-agent/typescript"
PY_SRC = ROOT / "lessons/00-workflow-or-agent/python/src"
OUTPUT_ROOT = ROOT / ".boundrelay/m0"
TRACE_ROOT = OUTPUT_ROOT / "traces"
EVIDENCE_PATH = OUTPUT_ROOT / "verification-evidence.json"
TERMINAL_TYPES = {"run.completed", "run.failed"}

_FORMAT_CHECKER = FormatChecker()


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _validator(path: Path) -> Draft202012Validator:
    return Draft202012Validator(_load_json(path), format_checker=_FORMAT_CHECKER)


def assert_clean_worktree() -> None:
    changes = subprocess.check_output(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        text=True,
    ).strip()
    if changes:
        raise RuntimeError(
            "Revision-bound verification requires a clean Git worktree. "
            "Commit or discard changes before running the M0 certification gate.\n"
            + changes
        )


def _revision() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def _runtime_version(command: list[str]) -> str:
    return subprocess.check_output(command, cwd=ROOT, text=True).strip()


def _run(command: list[str], *, env: Mapping[str, str] | None = None) -> dict[str, object]:
    process = subprocess.run(
        command,
        cwd=ROOT,
        env=dict(env) if env is not None else None,
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"Command failed ({process.returncode}): {' '.join(command)}\n"
            f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
        )
    lines = [line for line in process.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"Command produced no JSON result: {' '.join(command)}")
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Last stdout line was not JSON for {' '.join(command)}: {lines[-1]}"
        ) from error
    if not isinstance(result, dict):
        raise RuntimeError(f"CLI result must be a JSON object: {' '.join(command)}")
    return result


def _validate_document(
    validator: Draft202012Validator,
    value: dict[str, object],
    *,
    label: str,
) -> None:
    errors = sorted(
        validator.iter_errors(value),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if errors:
        details = "; ".join(
            f"/{'/'.join(str(part) for part in error.absolute_path)} {error.message}"
            for error in errors
        )
        raise AssertionError(f"{label} failed schema validation: {details}")


def _assert_trace(
    events: list[dict[str, object]],
    *,
    source: str,
    expected_run_id: str,
    label: str,
    event_validator: Draft202012Validator,
) -> None:
    for index, event in enumerate(events, start=1):
        _validate_document(event_validator, event, label=f"{label} event {index}")
        if event.get("source") != source:
            raise AssertionError(f"{label} event {index} has wrong source: {event.get('source')}")
        if event.get("run_id") != expected_run_id:
            raise AssertionError(f"{label} event {index} has wrong run_id: {event.get('run_id')}")
    sequences = [event.get("sequence") for event in events]
    expected = list(range(1, len(events) + 1))
    if sequences != expected:
        raise AssertionError(f"{label} has non-monotonic sequences: {sequences}")
    terminal = [event for event in events if event.get("type") in TERMINAL_TYPES]
    if len(terminal) != 1:
        raise AssertionError(f"{label} must contain exactly one terminal event")
    if events[-1].get("type") not in TERMINAL_TYPES:
        raise AssertionError(f"{label} terminal event must be last")


def _has_specialist_step(events: list[dict[str, object]]) -> bool:
    for event in events:
        data = event.get("data")
        if isinstance(data, dict) and str(data.get("step", "")).startswith("specialist."):
            return True
    return False


def _assert_expected_behavior(
    *,
    case: dict[str, object],
    result: dict[str, object],
    events: list[dict[str, object]],
    label: str,
) -> None:
    expected_route = case.get("expected_route")
    expected_failure = case.get("expected_failure_code")
    if expected_route is not None:
        expected = {
            "status": "SUCCEEDED",
            "selected_route": expected_route,
            "specialist_invoked": True,
            "failure_code": None,
        }
        for key, value in expected.items():
            if result.get(key) != value:
                raise AssertionError(f"{label} expected {key}={value!r}, got {result.get(key)!r}")
        if not _has_specialist_step(events):
            raise AssertionError(f"{label} did not emit a specialist step")
        if not any(event.get("type") == "route.selected" for event in events):
            raise AssertionError(f"{label} did not emit route.selected")
        return

    if expected_failure != "INVALID_ROUTE_DECISION":
        raise AssertionError(f"Unsupported failure expectation in {label}: {expected_failure}")
    expected = {
        "status": "FAILED",
        "selected_route": None,
        "specialist_invoked": False,
        "failure_code": "INVALID_ROUTE_DECISION",
    }
    for key, value in expected.items():
        if result.get(key) != value:
            raise AssertionError(f"{label} expected {key}={value!r}, got {result.get(key)!r}")
    if _has_specialist_step(events):
        raise AssertionError(f"{label} invoked a specialist after route rejection")
    if not any(event.get("type") == "route.rejected" for event in events):
        raise AssertionError(f"{label} did not emit route.rejected")


def _scenario_cases() -> list[tuple[dict[str, object], str]]:
    document = yaml.safe_load(SCENARIO_PATH.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("cases"), list):
        raise ValueError("Canonical support-triage scenario is invalid")
    combinations: list[tuple[dict[str, object], str]] = []
    for raw_case in document["cases"]:
        if not isinstance(raw_case, dict):
            raise ValueError("Scenario cases must be objects")
        case = dict(raw_case)
        if "expected_route" in case:
            combinations.append((case, "deterministic"))
            combinations.append((case, "model"))
        elif case.get("expected_failure_code") == "INVALID_ROUTE_DECISION":
            combinations.append((case, "model"))
        else:
            raise ValueError(f"Unsupported scenario expectation: {case}")
    if len(combinations) != 7:
        raise AssertionError(f"M0 must contain seven verification combinations, got {len(combinations)}")
    return combinations


def verify() -> dict[str, object]:
    assert_clean_worktree()
    shutil.rmtree(OUTPUT_ROOT, ignore_errors=True)
    TRACE_ROOT.mkdir(parents=True, exist_ok=True)

    event_validator = _validator(EVENT_SCHEMA_PATH)
    result_validator = _validator(RESULT_SCHEMA_PATH)
    python_env = os.environ.copy()
    existing_pythonpath = python_env.get("PYTHONPATH")
    python_env["PYTHONPATH"] = str(PY_SRC) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")

    records: list[dict[str, object]] = []
    for case, mode in _scenario_cases():
        case_id = case.get("id")
        if not isinstance(case_id, str):
            raise ValueError("Scenario case id must be a string")
        ts_trace = Path(".boundrelay/m0/traces") / f"{case_id}-{mode}-typescript.jsonl"
        py_trace = Path(".boundrelay/m0/traces") / f"{case_id}-{mode}-python.jsonl"

        ts_result = _run([
            "npm",
            "--prefix",
            str(TS_ROOT),
            "run",
            "run",
            "--",
            "--mode",
            mode,
            "--case",
            case_id,
            "--trace",
            str(ROOT / ts_trace),
        ])
        py_result = _run([
            sys.executable,
            "-m",
            "boundrelay_m0",
            "--mode",
            mode,
            "--case",
            case_id,
            "--trace",
            str(ROOT / py_trace),
        ], env=python_env)

        _validate_document(result_validator, ts_result, label=f"TypeScript {case_id}/{mode} result")
        _validate_document(result_validator, py_result, label=f"Python {case_id}/{mode} result")
        ts_events = read_jsonl(ROOT / ts_trace)
        py_events = read_jsonl(ROOT / py_trace)
        _assert_trace(
            ts_events,
            source="typescript",
            expected_run_id=str(ts_result["run_id"]),
            label=f"TypeScript {case_id}/{mode}",
            event_validator=event_validator,
        )
        _assert_trace(
            py_events,
            source="python",
            expected_run_id=str(py_result["run_id"]),
            label=f"Python {case_id}/{mode}",
            event_validator=event_validator,
        )
        _assert_expected_behavior(case=case, result=ts_result, events=ts_events, label=f"TypeScript {case_id}/{mode}")
        _assert_expected_behavior(case=case, result=py_result, events=py_events, label=f"Python {case_id}/{mode}")

        if normalize_result(ts_result) != normalize_result(py_result):
            raise AssertionError(f"Result parity failed for {case_id}/{mode}")
        if normalized_trace(ROOT / ts_trace) != normalized_trace(ROOT / py_trace):
            raise AssertionError(f"Trace parity failed for {case_id}/{mode}")

        records.append({
            "case_id": case_id,
            "mode": mode,
            "status": ts_result["status"],
            "typescript_trace": ts_trace.as_posix(),
            "python_trace": py_trace.as_posix(),
            "event_count": len(ts_events),
        })

    evidence: dict[str, object] = {
        "schema_version": "1.0",
        "revision": _revision(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "runtimes": {
            "python": platform.python_version(),
            "node": _runtime_version(["node", "--version"]),
            "npm": _runtime_version(["npm", "--version"]),
        },
        "verification_command": "python -m tools.parity.verify_m0",
        "status": "PASSED",
        "cases": records,
    }
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return evidence


def main() -> int:
    try:
        evidence = verify()
    except Exception as error:
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        failed = {
            "schema_version": "1.0",
            "revision": _revision(),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "verification_command": "python -m tools.parity.verify_m0",
            "status": "FAILED",
            "error": str(error),
        }
        EVIDENCE_PATH.write_text(json.dumps(failed, indent=2) + "\n", encoding="utf-8")
        print(str(error), file=sys.stderr)
        return 1
    print(f"M0 parity verified for {len(evidence['cases'])} combinations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
