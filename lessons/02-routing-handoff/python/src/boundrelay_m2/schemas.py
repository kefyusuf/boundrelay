from copy import deepcopy
import json
import math
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


def _finite(value, seen=None, depth=0):
    # Check JSON representability before schema diagnostics can render untrusted
    # objects. The small depth bound and safe integer range match this lesson's
    # JSON boundary and avoid recursion/huge-number formatting failures.
    if depth > 32:
        return False
    if value is None or type(value) in (str, bool):
        return True
    if type(value) is int:
        return -(2**53 - 1) <= value <= 2**53 - 1
    if type(value) is float:
        return math.isfinite(value)
    if type(value) not in (dict, list):
        return False
    seen = set() if seen is None else seen
    marker = id(value)
    if marker in seen:
        return False
    seen.add(marker)
    try:
        if type(value) is dict:
            return all(type(key) is str and _finite(item, seen, depth + 1) for key, item in value.items())
        return all(_finite(item, seen, depth + 1) for item in value)
    finally:
        seen.remove(marker)


def _validate_mapping(
    validator: Draft202012Validator,
    raw: object,
) -> ValidationResult[dict[str, object]]:
    if not _finite(raw):
        return ValidationFailure(("/ must be a finite, bounded JSON value",))
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
