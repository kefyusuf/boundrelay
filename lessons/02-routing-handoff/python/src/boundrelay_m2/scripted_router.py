from copy import deepcopy
from pathlib import Path
from typing import Mapping

import yaml

from .paths import FAKE_MODEL_PATH
from .types import RouteDecisionProvider


class ScriptedRouteError(RuntimeError):
    pass


class ScriptedRouteProvider(RouteDecisionProvider):
    def __init__(self, decisions: Mapping[str, object]) -> None:
        self._decisions = deepcopy(dict(decisions))
        self._consumed: set[str] = set()

    @classmethod
    def from_file(cls, path: Path = FAKE_MODEL_PATH) -> "ScriptedRouteProvider":
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if (
            not isinstance(raw, Mapping)
            or raw.get("schema_version") != "1.0"
            or raw.get("scenario_id") != "support-handoff"
            or not isinstance(raw.get("decisions"), Mapping)
        ):
            raise ScriptedRouteError("Unsupported M2 scripted route fixture.")
        decisions: dict[str, object] = {}
        for case_id, entry in cast_mapping(raw["decisions"]).items():
            if not isinstance(case_id, str) or not isinstance(entry, Mapping) or tuple(entry.keys()) != ("return",):
                raise ScriptedRouteError(f"Decision {case_id} must contain exactly return.")
            decisions[case_id] = deepcopy(entry["return"])
        return cls(decisions)

    async def next_decision(self, *, case_id: str, request: str) -> object:
        del request
        if case_id not in self._decisions:
            raise ScriptedRouteError(f"Missing scripted decision for case: {case_id}")
        if case_id in self._consumed:
            raise ScriptedRouteError(f"Scripted decision already consumed for case: {case_id}")
        self._consumed.add(case_id)
        return deepcopy(self._decisions[case_id])


def cast_mapping(value: object) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ScriptedRouteError("Scripted decisions must be an object.")
    return value
