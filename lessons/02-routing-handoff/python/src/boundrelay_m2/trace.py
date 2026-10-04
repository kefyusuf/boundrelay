from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from .schemas import validate_run_event
from .types import EventSource, EventType

Clock = callable


def _new_id() -> str:
    return str(uuid4())


def _json_safe(value: object, seen: set[int]) -> object:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, list):
        marker=id(value)
        if marker in seen: return None
        seen.add(marker)
        try: return [_json_safe(item, seen) for item in value]
        finally: seen.remove(marker)
    if isinstance(value, Mapping):
        marker=id(value)
        if marker in seen: return None
        seen.add(marker)
        try: return {str(key): _json_safe(item, seen) for key,item in value.items()}
        finally: seen.remove(marker)
    return None


def _safe_data(data: Mapping[str, object]) -> dict[str, object]:
    safe=_json_safe(dict(data),set())
    if not isinstance(safe, dict):
        raise ValueError("Event data must be a JSON object")
    return safe


class MemoryEventSink:
    def __init__(self, *, run_id: str, source: EventSource, clock=None, id_factory=None) -> None:
        self._run_id=run_id
        self._source=source
        self._clock=clock or (lambda: datetime.now(timezone.utc))
        self._id_factory=id_factory or _new_id
        self._events: list[dict[str, object]]=[]
        self._sequence=0

    @property
    def events(self) -> tuple[dict[str, object], ...]:
        return tuple(deepcopy(self._events))

    def emit(self, event_type: EventType, data: Mapping[str, object]) -> dict[str, object]:
        self._sequence += 1
        event={
            "schema_version":"1.0",
            "event_id":self._id_factory(),
            "run_id":self._run_id,
            "sequence":self._sequence,
            "type":event_type,
            "timestamp":self._clock().isoformat().replace("+00:00","Z"),
            "source":self._source,
            "data":_safe_data(data),
        }
        validation=validate_run_event(event)
        if not validation.ok:
            raise ValueError(f"Invalid run event: {'; '.join(validation.errors)}")
        snapshot=deepcopy(validation.value)
        self._events.append(snapshot)
        return deepcopy(snapshot)


def write_jsonl(path: str | Path, events: tuple[dict[str, object], ...] | list[dict[str, object]]) -> None:
    target=Path(path)
    target.parent.mkdir(parents=True,exist_ok=True)
    content="\n".join(json.dumps(event,separators=(",",":"),allow_nan=False) for event in events)+"\n"
    target.write_bytes(content.encode("utf-8"))
