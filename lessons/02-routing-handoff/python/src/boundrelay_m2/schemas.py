from copy import deepcopy
import json
from pathlib import Path
from typing import Mapping

from jsonschema import Draft202012Validator, FormatChecker

from .paths import EVENT_SCHEMA_PATH, HANDOFF_SCHEMA_PATH, RESULT_SCHEMA_PATH, ROUTE_SCHEMA_PATH
from .types import ValidationFailure, ValidationResult, ValidationSuccess


def _load_schema(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Schema must be an object: {path}")
    return value


_FORMAT_CHECKER = FormatChecker()
_ROUTE_VALIDATOR = Draft202012Validator(_load_schema(ROUTE_SCHEMA_PATH), format_checker=_FORMAT_CHECKER)
_HANDOFF_VALIDATOR = Draft202012Validator(_load_schema(HANDOFF_SCHEMA_PATH), format_checker=_FORMAT_CHECKER)
_EVENT_VALIDATOR = Draft202012Validator(_load_schema(EVENT_SCHEMA_PATH), format_checker=_FORMAT_CHECKER)
_RESULT_VALIDATOR = Draft202012Validator(_load_schema(RESULT_SCHEMA_PATH), format_checker=_FORMAT_CHECKER)


def _stable_errors(validator: Draft202012Validator, raw: object) -> tuple[str, ...]:
    errors = sorted(validator.iter_errors(raw), key=lambda error: (list(error.absolute_path), error.message))
    values: list[str] = []
    for error in errors:
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        values.append(f"{path or '/'} {error.message}")
    return tuple(values)


def _validate_mapping(
    validator: Draft202012Validator,
    raw: object,
) -> ValidationResult[dict[str, object]]:
    errors = _stable_errors(validator, raw)
    if errors:
        return ValidationFailure(errors)
    if not isinstance(raw, Mapping):
        return ValidationFailure(("/ must be an object",))
    return ValidationSuccess(deepcopy(dict(raw)))


def validate_route_decision(value: object) -> ValidationResult[dict[str, object]]:
    return _validate_mapping(_ROUTE_VALIDATOR, value)


def validate_handoff(value: object) -> ValidationResult[dict[str, object]]:
    return _validate_mapping(_HANDOFF_VALIDATOR, value)


def validate_run_event(value: object) -> ValidationResult[dict[str, object]]:
    return _validate_mapping(_EVENT_VALIDATOR, value)


def validate_run_result(value: object) -> ValidationResult[dict[str, object]]:
    return _validate_mapping(_RESULT_VALIDATOR, value)
