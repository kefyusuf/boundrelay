from copy import deepcopy
from pathlib import Path
from typing import Mapping

import yaml

from .paths import FAKE_MODEL_PATH


class ScriptedDecisionProvider:
    def __init__(self, responses: Mapping[str, object]) -> None:
        self._responses = deepcopy(dict(responses))

    @classmethod
    def from_file(cls, path: Path = FAKE_MODEL_PATH) -> "ScriptedDecisionProvider":
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if (
            not isinstance(document, Mapping)
            or document.get("schema_version") != "1.0"
            or document.get("scenario_id") != "support-triage"
        ):
            raise ValueError("Unsupported scripted decision fixture.")
        entries = document.get("responses")
        if not isinstance(entries, Mapping):
            raise ValueError("Scripted decision fixture must contain a responses object.")
        responses: dict[str, object] = {}
        for case_id, entry in entries.items():
            if not isinstance(case_id, str) or not isinstance(entry, Mapping) or "return" not in entry:
                raise ValueError(f"Scripted response {case_id} must contain a return value.")
            responses[case_id] = deepcopy(entry["return"])
        return cls(responses)

    def classify(self, *, case_id: str, request: str) -> object:
        del request
        if case_id not in self._responses:
            raise ValueError(f"Missing scripted decision for case: {case_id}")
        return deepcopy(self._responses[case_id])
