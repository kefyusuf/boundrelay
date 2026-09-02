from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one target, got {count}")
    return text.replace(old, new)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-m0-lifecycle-review-fixes.py <target-repository>")

    path = Path(sys.argv[1]) / "tools/parity/verify_m0.py"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        'TERMINAL_TYPES = {"run.completed", "run.failed"}\n\n_FORMAT_CHECKER',
        '''TERMINAL_TYPES = {"run.completed", "run.failed"}
EXPECTED_LIFECYCLE_SEQUENCES: dict[tuple[str, str], tuple[str, ...]] = {
    ("deterministic", "SUCCEEDED"): (
        "run.created",
        "run.started",
        "step.started",
        "route.selected",
        "step.completed",
        "step.started",
        "step.completed",
        "run.completed",
    ),
    ("model", "SUCCEEDED"): (
        "run.created",
        "run.started",
        "step.started",
        "model.requested",
        "model.completed",
        "route.selected",
        "step.completed",
        "step.started",
        "step.completed",
        "run.completed",
    ),
    ("model", "FAILED"): (
        "run.created",
        "run.started",
        "step.started",
        "model.requested",
        "model.completed",
        "route.rejected",
        "step.failed",
        "run.failed",
    ),
}

_FORMAT_CHECKER''',
        "lifecycle constants",
    )

    helpers = '''

def _assert_lifecycle_sequence(
    events: list[dict[str, object]],
    *,
    mode: str,
    expected_status: object,
    label: str,
) -> None:
    key = (mode, str(expected_status))
    expected = EXPECTED_LIFECYCLE_SEQUENCES.get(key)
    if expected is None:
        raise AssertionError(f"{label} has unsupported lifecycle path: {key}")
    actual = tuple(str(event.get("type")) for event in events)
    if actual != expected:
        raise AssertionError(
            f"{label} event sequence does not match the canonical M0 lifecycle: "
            f"expected {list(expected)}, got {list(actual)}"
        )


def _assert_trace_context(
    events: list[dict[str, object]],
    *,
    expected_case_id: str,
    expected_mode: str,
    label: str,
) -> None:
    if len(events) < 3:
        raise AssertionError(f"{label} trace is too short for lifecycle context")

    created_data = events[0].get("data")
    expected_created = {
        "scenario_id": SCENARIO_ID,
        "case_id": expected_case_id,
        "mode": expected_mode,
    }
    if not isinstance(created_data, dict) or any(
        created_data.get(key) != value for key, value in expected_created.items()
    ):
        raise AssertionError(
            f"{label} run.created context must match {expected_created}, got {created_data!r}"
        )

    started_data = events[1].get("data")
    expected_started = {
        "case_id": expected_case_id,
        "mode": expected_mode,
    }
    if not isinstance(started_data, dict) or any(
        started_data.get(key) != value for key, value in expected_started.items()
    ):
        raise AssertionError(
            f"{label} run.started context must match {expected_started}, got {started_data!r}"
        )

    classify_started = [
        event for event in events
        if event.get("type") == "step.started"
        and isinstance(event.get("data"), dict)
        and event["data"].get("step") == "classify"
    ]
    classify_finished = [
        event for event in events
        if event.get("type") in {"step.completed", "step.failed"}
        and isinstance(event.get("data"), dict)
        and event["data"].get("step") == "classify"
    ]
    if len(classify_started) != 1 or len(classify_finished) != 1:
        raise AssertionError(
            f"{label} must contain exactly one classify start and one classify completion/failure"
        )

    if expected_mode == "model":
        for event_type in ("model.requested", "model.completed"):
            matching = [event for event in events if event.get("type") == event_type]
            if len(matching) != 1:
                raise AssertionError(f"{label} must contain exactly one {event_type} event")
            data = matching[0].get("data")
            if not isinstance(data, dict) or data.get("case_id") != expected_case_id:
                raise AssertionError(
                    f"{label} {event_type} context has wrong case_id: {data!r}"
                )
'''
    text = replace_once(
        text,
        "\n\ndef _assert_terminal_status(\n",
        helpers + "\n\ndef _assert_terminal_status(\n",
        "lifecycle helpers",
    )

    old_calls = '''        _assert_trace(
            py_events,
            source="python",
            expected_run_id=str(py_result["run_id"]),
            label=py_label,
            event_validator=event_validator,
        )
        _assert_terminal_status(
'''
    new_calls = '''        _assert_trace(
            py_events,
            source="python",
            expected_run_id=str(py_result["run_id"]),
            label=py_label,
            event_validator=event_validator,
        )
        _assert_lifecycle_sequence(
            ts_events,
            mode=mode,
            expected_status=ts_result["status"],
            label=ts_label,
        )
        _assert_lifecycle_sequence(
            py_events,
            mode=mode,
            expected_status=py_result["status"],
            label=py_label,
        )
        _assert_trace_context(
            ts_events,
            expected_case_id=case_id,
            expected_mode=mode,
            label=ts_label,
        )
        _assert_trace_context(
            py_events,
            expected_case_id=case_id,
            expected_mode=mode,
            label=py_label,
        )
        _assert_terminal_status(
'''
    text = replace_once(text, old_calls, new_calls, "lifecycle calls")

    path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
