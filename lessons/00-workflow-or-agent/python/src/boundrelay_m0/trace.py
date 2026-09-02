from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import cast
from uuid import uuid4

from .schemas import validate_run_event
from .types import EventSource, EventType

Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid4())


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    raise TypeError(f"Event data must be JSON-compatible, got {type(value).__name__}")


class MemoryEventSink:
    def __init__(
        self,
        *,
        run_id: str,
        source: EventSource,
        clock: Clock | None = None,
        id_factory: IdFactory | None = None,
    ) -> None:
        self._run_id = run_id
        self._source = source
        self._clock = clock or _utc_now
        self._id_factory = id_factory or _new_id
        self._events: list[dict[str, object]] = []
        self._sequence = 0

    @property
    def events(self) -> tuple[dict[str, object], ...]:
        return tuple(deepcopy(self._events))

    def emit(self, event_type: EventType, data: Mapping[str, object]) -> dict[str, object]:
        self._sequence += 1
        safe_data = _json_safe(dict(data))
        if not isinstance(safe_data, dict):
            raise TypeError("Event data must be a JSON object")
        event: dict[str, object] = {
            "schema_version": "1.0",
            "event_id": self._id_factory(),
            "run_id": self._run_id,
            "sequence": self._sequence,
            "type": event_type,
            "timestamp": _timestamp(self._clock()),
            "source": self._source,
            "data": safe_data,
        }
        validation = validate_run_event(event)
        if not validation.ok:
            raise ValueError(f"Invalid run event: {'; '.join(validation.errors)}")
        snapshot = validation.value
        self._events.append(deepcopy(snapshot))
        return deepcopy(snapshot)


def write_jsonl(path: str | Path, events: Sequence[Mapping[str, object]]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        json.dumps(
            dict(event),
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        for event in events
    ) + "\n"
    destination.write_text(content, encoding="utf-8")
