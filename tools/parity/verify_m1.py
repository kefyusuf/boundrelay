from __future__ import annotations

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
SCENARIO_ID = "order-investigation"
SCENARIO_PATH = ROOT / "fixtures/scenarios/order-investigation.yaml"
EVENT_SCHEMA_PATH = ROOT / "contracts/events/run-event.schema.json"
RESULT_SCHEMA_PATH = ROOT / "contracts/results/tool-loop-result.schema.json"
TS_ROOT = ROOT / "lessons/01-bounded-tool-loop/typescript"
PY_SRC = ROOT / "lessons/01-bounded-tool-loop/python/src"
OUTPUT_ROOT = ROOT / ".boundrelay/m1"
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


def assert_clean_worktree() -> None:
    changes = subprocess.check_output(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        text=True,
    ).strip()
    if changes:
        raise RuntimeError(
            "Revision-bound verification requires a clean Git worktree. "
            "Commit or discard changes before running the M1 certification gate.\n"
            + changes
        )


def _revision() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _runtime_version(command: list[str]) -> str:
    return subprocess.check_output([shutil.which(command[0]) or command[0], *command[1:]], cwd=ROOT, text=True).strip()


def _run(command: list[str], *, env: Mapping[str, str] | None = None) -> dict[str, object]:
    command = [shutil.which(command[0]) or command[0], *command[1:]]
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
    if len(lines) != 1:
        raise RuntimeError(
            f"Command must produce exactly one nonblank stdout line: {' '.join(command)}; got {len(lines)}"
        )
    try:
        result = json.loads(lines[0])
    except json.JSONDecodeError as error:
        raise RuntimeError(f"CLI stdout was not JSON for {' '.join(command)}: {lines[0]}") from error
    if not isinstance(result, dict):
        raise RuntimeError(f"CLI result must be a JSON object: {' '.join(command)}")
    return result


def _scenario_cases() -> list[dict[str, object]]:
    value = yaml.safe_load(SCENARIO_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != "1.0" or value.get("scenario_id") != SCENARIO_ID:
        raise AssertionError("Unsupported M1 scenario document")
    raw_cases = value.get("cases")
    if not isinstance(raw_cases, list):
        raise AssertionError("M1 scenario cases must be an array")
    cases: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in raw_cases:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not isinstance(raw.get("mode"), str):
            raise AssertionError("Each M1 scenario case must define string id and mode")
        case_id = str(raw["id"])
        if case_id in seen:
            raise AssertionError(f"Duplicate M1 case id: {case_id}")
        seen.add(case_id)
        cases.append(dict(raw))
    expected = {
        "direct-order-status",
        "agent-delayed-shipment",
        "agent-unknown-tool",
        "agent-invalid-arguments",
        "agent-tool-timeout",
        "agent-tool-failure",
        "agent-step-budget",
        "agent-token-budget",
    }
    if seen != expected:
        raise AssertionError(f"M1 verifier requires exactly the canonical case set: {sorted(expected)}")
    return cases


def _assert_result_context(
    result: dict[str, object],
    *,
    expected_case_id: str,
    expected_mode: str,
    expected_trace_path: str,
    label: str,
) -> None:
    if result.get("case_id") != expected_case_id:
        raise AssertionError(f"{label} has wrong case_id: {result.get('case_id')!r}; expected {expected_case_id!r}")
    if result.get("mode") != expected_mode:
        raise AssertionError(f"{label} has wrong mode: {result.get('mode')!r}; expected {expected_mode!r}")
    if result.get("trace_path") != expected_trace_path:
        raise AssertionError(f"{label} has wrong trace_path: {result.get('trace_path')!r}; expected {expected_trace_path!r}")


def _assert_trace_integrity(
    events: list[dict[str, object]],
    *,
    expected_run_id: str,
    expected_source: str,
    label: str,
    event_validator: Draft202012Validator | None = None,
    validate_schema: bool = True,
) -> None:
    if not events:
        raise AssertionError(f"{label} trace is empty")
    for index, event in enumerate(events, start=1):
        if validate_schema:
            if event_validator is None:
                raise ValueError("event_validator is required when validate_schema=True")
            _validate_document(event_validator, event, label=f"{label} event {index}")
        if event.get("run_id") != expected_run_id:
            raise AssertionError(f"{label} event {index} has wrong run_id: {event.get('run_id')!r}")
        if event.get("source") != expected_source:
            raise AssertionError(f"{label} event {index} has wrong source: {event.get('source')!r}")
    sequences = [event.get("sequence") for event in events]
    expected_sequences = list(range(1, len(events) + 1))
    if sequences != expected_sequences:
        raise AssertionError(f"{label} has non-monotonic sequences: {sequences}")
    terminals = [index for index, event in enumerate(events) if event.get("type") in TERMINAL_TYPES]
    if not terminals:
        raise AssertionError(f"{label} must contain exactly one terminal event")
    if terminals[-1] != len(events) - 1:
        raise AssertionError(f"{label} terminal event must be last")
    if len(terminals) != 1:
        raise AssertionError(f"{label} must contain exactly one terminal event")


def _event_data(event: dict[str, object]) -> dict[str, object]:
    data = event.get("data")
    return data if isinstance(data, dict) else {}


def _tool_requested_names(events: list[dict[str, object]]) -> list[str]:
    return [
        str(_event_data(event).get("tool"))
        for event in events
        if event.get("type") == "tool.requested"
    ]


def _assert_terminal_matches_result(
    events: list[dict[str, object]],
    result: dict[str, object],
    *,
    label: str,
) -> None:
    terminals = [event for event in events if event.get("type") in TERMINAL_TYPES]
    if not terminals:
        return
    terminal = terminals[-1]
    data = _event_data(terminal)
    expected_type = "run.completed" if result.get("status") == "SUCCEEDED" else "run.failed"
    if terminal.get("type") != expected_type:
        raise AssertionError(f"{label} terminal type does not match result status")
    for key in ("status", "model_steps", "tokens_used", "tool_invocations"):
        if data.get(key) != result.get(key):
            raise AssertionError(f"{label} terminal payload has wrong {key}")
    if result.get("status") == "SUCCEEDED":
        if data.get("answer") != result.get("answer"):
            raise AssertionError(f"{label} terminal payload has wrong answer")
    elif data.get("failure_code") != result.get("failure_code"):
        raise AssertionError(f"{label} terminal payload has wrong failure_code")


def _assert_case_behavior(
    *,
    case: dict[str, object],
    result: dict[str, object],
    events: list[dict[str, object]],
    label: str,
) -> None:
    expected_status = case.get("expected_status")
    if result.get("status") != expected_status:
        raise AssertionError(f"{label} has wrong status: {result.get('status')!r}; expected {expected_status!r}")
    for key in ("model_steps", "tokens_used", "tool_invocations"):
        expected_key = f"expected_{key}"
        if result.get(key) != case.get(expected_key):
            raise AssertionError(f"{label} has wrong {key}: {result.get(key)!r}; expected {case.get(expected_key)!r}")

    if expected_status == "SUCCEEDED":
        if result.get("answer") != case.get("expected_answer") or result.get("failure_code") is not None:
            raise AssertionError(f"{label} success result does not match canonical answer/failure boundary")
    else:
        if result.get("answer") is not None or result.get("failure_code") != case.get("expected_failure_code"):
            raise AssertionError(f"{label} failure result does not match canonical failure boundary")

    requested = _tool_requested_names(events)
    expected_invocations = int(case.get("expected_tool_invocations", 0))
    if len(requested) != expected_invocations:
        raise AssertionError(
            f"{label} tool.requested count is {len(requested)}; expected {expected_invocations}"
        )

    mode = case.get("mode")
    if mode == "direct" and any(str(event.get("type", "")).startswith("model.") for event in events):
        raise AssertionError(f"{label} direct mode emitted model events")

    failure_code = case.get("expected_failure_code")
    if failure_code in {"UNKNOWN_TOOL", "INVALID_TOOL_ARGUMENTS"} and requested:
        raise AssertionError(f"{label} rejected decision emitted tool.requested")

    if failure_code in {"TOOL_TIMEOUT", "TOOL_EXECUTION_FAILED"}:
        failed = [event for event in events if event.get("type") == "tool.failed"]
        if len(failed) != 1 or _event_data(failed[0]).get("failure_code") != failure_code:
            raise AssertionError(f"{label} must emit exactly one tool.failed with {failure_code}")

    if failure_code in {"STEP_BUDGET_EXCEEDED", "TOKEN_BUDGET_EXCEEDED"}:
        exceeded = [event for event in events if event.get("type") == "budget.exceeded"]
        budget = "step" if failure_code == "STEP_BUDGET_EXCEEDED" else "token"
        if len(exceeded) != 1:
            raise AssertionError(f"{label} must emit exactly one budget.exceeded")
        data = _event_data(exceeded[0])
        if data.get("budget") != budget or data.get("failure_code") != failure_code:
            raise AssertionError(f"{label} budget.exceeded does not match {failure_code}")

    if case.get("id") == "agent-delayed-shipment":
        if requested != ["lookup_order", "lookup_shipment"]:
            raise AssertionError(f"{label} successful tool path must be lookup_order -> lookup_shipment")
        completed = [event for event in events if event.get("type") == "model.completed"]
        if not completed:
            raise AssertionError(f"{label} successful agent trace must contain model.completed")
        final_turn = _event_data(completed[-1]).get("turn")
        decision = final_turn.get("decision") if isinstance(final_turn, dict) else None
        if not isinstance(decision, dict) or decision.get("kind") != "final":
            raise AssertionError(f"{label} successful agent path must end with final model decision")

    _assert_terminal_matches_result(events, result, label=label)


def _assert_trace_context(
    events: list[dict[str, object]],
    *,
    expected_case_id: str,
    expected_mode: str,
    label: str,
) -> None:
    if len(events) < 3:
        raise AssertionError(f"{label} trace is too short")
    created = _event_data(events[0])
    started = _event_data(events[1])
    expected_created = {"scenario_id": SCENARIO_ID, "case_id": expected_case_id, "mode": expected_mode}
    expected_started = {"case_id": expected_case_id, "mode": expected_mode}
    if events[0].get("type") != "run.created" or any(created.get(k) != v for k, v in expected_created.items()):
        raise AssertionError(f"{label} run.created context does not match requested case")
    if events[1].get("type") != "run.started" or any(started.get(k) != v for k, v in expected_started.items()):
        raise AssertionError(f"{label} run.started context does not match requested case")


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def verify() -> dict[str, object]:
    assert_clean_worktree()
    revision = _revision()
    runtimes = {
        "node": _runtime_version(["node", "--version"]),
        "npm": _runtime_version(["npm", "--version"]),
        "python": platform.python_version(),
    }
    event_validator = _validator(EVENT_SCHEMA_PATH)
    result_validator = _validator(RESULT_SCHEMA_PATH)
    cases = _scenario_cases()
    TRACE_ROOT.mkdir(parents=True, exist_ok=True)
    evidence_cases: list[dict[str, object]] = []
    py_env = os.environ.copy()
    py_env["PYTHONPATH"] = str(PY_SRC)

    for case in cases:
        case_id = str(case["id"])
        mode = str(case["mode"])
        ts_trace = TRACE_ROOT / f"{case_id}-typescript.jsonl"
        py_trace = TRACE_ROOT / f"{case_id}-python.jsonl"
        # npm --prefix executes the TypeScript script from the package directory.
        # Pass absolute trace paths to both CLIs so trace placement does not depend
        # on runtime-specific working-directory behavior.
        ts_trace_arg = str(ts_trace)
        py_trace_arg = str(py_trace)

        ts_result = _run([
            "npm", "--silent", "--prefix", str(TS_ROOT), "run", "run", "--",
            "--mode", mode, "--case", case_id, "--trace", ts_trace_arg,
        ])
        py_result = _run([
            sys.executable, "-m", "boundrelay_m1",
            "--mode", mode, "--case", case_id, "--trace", py_trace_arg,
        ], env=py_env)

        _validate_document(result_validator, ts_result, label=f"TypeScript {case_id} result")
        _validate_document(result_validator, py_result, label=f"Python {case_id} result")
        _assert_result_context(
            ts_result, expected_case_id=case_id, expected_mode=mode,
            expected_trace_path=ts_trace_arg, label=f"TypeScript {case_id}",
        )
        _assert_result_context(
            py_result, expected_case_id=case_id, expected_mode=mode,
            expected_trace_path=py_trace_arg, label=f"Python {case_id}",
        )

        ts_events = read_jsonl(ts_trace)
        py_events = read_jsonl(py_trace)
        _assert_trace_integrity(
            ts_events, expected_run_id=str(ts_result["run_id"]), expected_source="typescript",
            label=f"TypeScript {case_id}", event_validator=event_validator,
        )
        _assert_trace_integrity(
            py_events, expected_run_id=str(py_result["run_id"]), expected_source="python",
            label=f"Python {case_id}", event_validator=event_validator,
        )
        _assert_trace_context(ts_events, expected_case_id=case_id, expected_mode=mode, label=f"TypeScript {case_id}")
        _assert_trace_context(py_events, expected_case_id=case_id, expected_mode=mode, label=f"Python {case_id}")
        _assert_case_behavior(case=case, result=ts_result, events=ts_events, label=f"TypeScript {case_id}")
        _assert_case_behavior(case=case, result=py_result, events=py_events, label=f"Python {case_id}")

        if normalize_result(ts_result) != normalize_result(py_result):
            raise AssertionError(f"{case_id} normalized results differ between TypeScript and Python")
        if normalized_trace(ts_trace) != normalized_trace(py_trace):
            raise AssertionError(f"{case_id} normalized traces differ between TypeScript and Python")

        evidence_cases.append({
            "case_id": case_id,
            "mode": mode,
            "status": ts_result.get("status"),
            "failure_code": ts_result.get("failure_code"),
            "model_steps": ts_result.get("model_steps"),
            "tokens_used": ts_result.get("tokens_used"),
            "tool_invocations": ts_result.get("tool_invocations"),
            "typescript_trace": _relative(ts_trace),
            "python_trace": _relative(py_trace),
        })

    assert_clean_worktree()
    final_revision = _revision()
    if final_revision != revision:
        raise RuntimeError(f"Candidate revision changed during M1 verification: {revision} -> {final_revision}")

    evidence: dict[str, object] = {
        "schema_version": "1.0",
        "scenario_id": SCENARIO_ID,
        "status": "PASSED",
        "revision": revision,
        "command": "python scripts/verify_m1.py",
        "runtimes": runtimes,
        "cases": evidence_cases,
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def main() -> int:
    evidence = verify()
    print(json.dumps(evidence, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
