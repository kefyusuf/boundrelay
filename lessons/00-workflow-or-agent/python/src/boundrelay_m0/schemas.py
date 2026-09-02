from copy import deepcopy
from dataclasses import dataclass
import json
import math
from typing import Generic, Literal, Mapping, TypeVar, cast

from jsonschema import Draft202012Validator, FormatChecker

from .paths import EVENT_SCHEMA_PATH, RESULT_SCHEMA_PATH, ROUTE_SCHEMA_PATH
from .types import Route, RouteDecision

T = TypeVar("T")


@dataclass(frozen=True)
class ValidationSuccess(Generic[T]):
    value: T

    @property
    def ok(self) -> Literal[True]:
        return True


@dataclass(frozen=True)
class ValidationFailure:
    errors: tuple[str, ...]

    @property
    def ok(self) -> Literal[False]:
        return False


ValidationResult = ValidationSuccess[T] | ValidationFailure


def _load_schema(path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Schema must be an object: {path}")
    return value


_FORMAT_CHECKER = FormatChecker()
_ROUTE_VALIDATOR = Draft202012Validator(_load_schema(ROUTE_SCHEMA_PATH), format_checker=_FORMAT_CHECKER)
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
) -> ValidationSuccess[dict[str, object]] | ValidationFailure:
    errors = _stable_errors(validator, raw)
    if errors:
        return ValidationFailure(errors)
    if not isinstance(raw, Mapping):
        return ValidationFailure(("/ must be an object",))
    return ValidationSuccess(deepcopy(dict(raw)))


def validate_route_decision(raw: object) -> ValidationSuccess[RouteDecision] | ValidationFailure:
    if isinstance(raw, Mapping):
        confidence = raw.get("confidence")
        if isinstance(confidence, int) and not isinstance(confidence, bool):
            if confidence < 0 or confidence > 1:
                return ValidationFailure(("/confidence must be between 0 and 1",))
        elif isinstance(confidence, float) and not math.isfinite(confidence):
            return ValidationFailure(("/confidence must be a finite number",))

    validated = _validate_mapping(_ROUTE_VALIDATOR, raw)
    if not validated.ok:
        return validated
    value = validated.value
    return ValidationSuccess(RouteDecision(cast(Route, value["route"]), float(value["confidence"])))


def validate_run_event(raw: object) -> ValidationSuccess[dict[str, object]] | ValidationFailure:
    return _validate_mapping(_EVENT_VALIDATOR, raw)


def validate_run_result(raw: object) -> ValidationSuccess[dict[str, object]] | ValidationFailure:
    return _validate_mapping(_RESULT_VALIDATOR, raw)
