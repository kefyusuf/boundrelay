from copy import deepcopy
from pathlib import Path
from typing import Mapping

import yaml

from .paths import FAKE_MODEL_PATH
from .types import ModelProvider, ToolObservation


class ScriptedModelError(RuntimeError):
    pass


class ScriptedModelProvider(ModelProvider):
    def __init__(self, trajectories: Mapping[str, tuple[object, ...]]) -> None:
        self._trajectories = deepcopy(dict(trajectories))
        self._next_steps: dict[str, int] = {}

    @classmethod
    def from_file(cls, path: Path = FAKE_MODEL_PATH) -> "ScriptedModelProvider":
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if (
            not isinstance(document, Mapping)
            or document.get("schema_version") != "1.0"
            or document.get("scenario_id") != "order-investigation"
        ):
            raise ScriptedModelError("Unsupported M1 scripted model fixture.")
        raw_trajectories = document.get("trajectories")
        if not isinstance(raw_trajectories, Mapping):
            raise ScriptedModelError("Scripted model fixture must contain trajectories.")
        trajectories: dict[str, tuple[object, ...]] = {}
        for case_id, raw_turns in raw_trajectories.items():
            if not isinstance(case_id, str) or not isinstance(raw_turns, list) or not raw_turns:
                raise ScriptedModelError(f"Trajectory {case_id} must be a non-empty array.")
            turns: list[object] = []
            for entry in raw_turns:
                if not isinstance(entry, Mapping) or "return" not in entry:
                    raise ScriptedModelError(f"Trajectory {case_id} entries must contain return values.")
                turns.append(deepcopy(entry["return"]))
            trajectories[case_id] = tuple(turns)
        return cls(trajectories)

    async def next_turn(
        self,
        *,
        case_id: str,
        request: str,
        model_step: int,
        observations: tuple[ToolObservation, ...],
    ) -> object:
        del request, observations
        trajectory = self._trajectories.get(case_id)
        if trajectory is None:
            raise ScriptedModelError(f"Missing scripted trajectory for case: {case_id}")
        expected_step = self._next_steps.get(case_id, 1)
        if model_step != expected_step:
            raise ScriptedModelError(
                f"Out-of-order scripted turn for {case_id}: expected {expected_step}, got {model_step}."
            )
        index = model_step - 1
        if index >= len(trajectory):
            raise ScriptedModelError(f"Scripted trajectory exhausted for {case_id} at step {model_step}.")
        self._next_steps[case_id] = expected_step + 1
        return deepcopy(trajectory[index])
