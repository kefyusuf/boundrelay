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
    content = source.read_text(encoding="utf-8")
    if not content:
        raise ValueError(f"JSONL trace is empty: {source}")

    # JSONL records are delimited by LF only. Preserve Unicode characters such
    # as U+0085/U+2028/U+2029 when they occur inside JSON strings. Accept the
    # single terminal LF emitted by both runtimes and normalize CRLF records.
    if content.endswith("\n"):
        content = content[:-1]
    if not content:
        raise ValueError(f"JSONL trace is empty: {source}")

    lines = content.split("\n")
    events: list[dict[str, object]] = []
    for number, raw_line in enumerate(lines, start=1):
        line = raw_line[:-1] if raw_line.endswith("\r") else raw_line
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
