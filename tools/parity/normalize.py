import json
from pathlib import Path

VOLATILE_EVENT_FIELDS = {"event_id", "run_id", "timestamp", "source"}
VOLATILE_RESULT_FIELDS = {"run_id", "trace_path"}


def normalize_event(event: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in event.items() if key not in VOLATILE_EVENT_FIELDS}


def normalize_result(result: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in result.items() if key not in VOLATILE_RESULT_FIELDS}


def read_jsonl(path: str | Path) -> list[dict[str, object]]:
    source = Path(path)
    lines = [line for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise ValueError(f"JSONL trace is empty: {source}")
    events: list[dict[str, object]] = []
    for number, line in enumerate(lines, start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSON on line {number} of {source}: {error.msg}") from error
        if not isinstance(value, dict):
            raise ValueError(f"JSONL line {number} of {source} must contain an object")
        events.append(value)
    return events


def normalized_trace(path: str | Path) -> list[dict[str, object]]:
    return [normalize_event(event) for event in read_jsonl(path)]
