import json
from pathlib import Path

VOLATILE_EVENT_FIELDS = {"event_id", "run_id", "timestamp", "source"}
VOLATILE_RESULT_FIELDS = {"run_id", "trace_path"}


def normalize_event(event: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in event.items() if key not in VOLATILE_EVENT_FIELDS}


def normalize_result(result: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in result.items() if key not in VOLATILE_RESULT_FIELDS}


def _reject_nonstandard_constant(value: str) -> object:
    raise ValueError(f"non-standard JSON constant: {value}")


def read_jsonl(path: str | Path) -> list[dict[str, object]]:
    source = Path(path)
    content = source.read_bytes().decode("utf-8")
    if not content:
        raise ValueError(f"JSONL trace is empty: {source}")

    # JSONL records are delimited by LF only. Read raw UTF-8 bytes so Python's
    # universal-newline layer cannot convert bare CR into LF before validation.
    # A CR is accepted only when it is immediately followed by a real LF.
    had_terminal_lf = content.endswith("\n")
    if had_terminal_lf:
        content = content[:-1]
    if not content:
        raise ValueError(f"JSONL trace is empty: {source}")

    lines = content.split("\n")
    events: list[dict[str, object]] = []
    for number, raw_line in enumerate(lines, start=1):
        terminated_by_lf = number < len(lines) or had_terminal_lf
        line = raw_line
        if line.endswith("\r"):
            if not terminated_by_lf:
                raise ValueError(f"bare CR record separator on line {number} of {source}")
            line = line[:-1]
        if "\r" in line:
            raise ValueError(f"bare CR record separator on line {number} of {source}")
        if not line.strip():
            raise ValueError(f"blank JSONL record on line {number} of {source}")
        try:
            value = json.loads(line, parse_constant=_reject_nonstandard_constant)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSON on line {number} of {source}: {error.msg}") from error
        except ValueError as error:
            raise ValueError(f"Invalid JSON on line {number} of {source}: {error}") from error
        if not isinstance(value, dict):
            raise ValueError(f"JSONL line {number} of {source} must contain an object")
        events.append(value)
    return events


def normalized_trace(path: str | Path) -> list[dict[str, object]]:
    return [normalize_event(event) for event in read_jsonl(path)]
