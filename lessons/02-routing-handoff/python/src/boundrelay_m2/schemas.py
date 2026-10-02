from copy import deepcopy
import json
import math
from jsonschema import Draft202012Validator, FormatChecker
from .paths import EVENT_SCHEMA_PATH, RESULT_SCHEMA_PATH, HANDOFF_SCHEMA_PATH, ROUTE_SCHEMA_PATH
from .types import ValidationResult


def _validator(path):
    return Draft202012Validator(json.loads(path.read_text(encoding='utf-8')), format_checker=FormatChecker())


def _finite(value):
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(_finite(item) for item in value)
    return True


def _validate(schema, value):
    if not _finite(value):
        return ValidationResult(False, errors=('/ non-finite number',))
    errors = tuple(f"/{'/'.join(map(str, e.absolute_path))} {e.message}" for e in schema.iter_errors(value))
    return ValidationResult(False, errors=errors) if errors else ValidationResult(True, deepcopy(value))


_route = _validator(ROUTE_SCHEMA_PATH)
_handoff = _validator(HANDOFF_SCHEMA_PATH)
_event = _validator(EVENT_SCHEMA_PATH)
_result = _validator(RESULT_SCHEMA_PATH)


def validate_route_decision(value): return _validate(_route, value)
def validate_handoff(value): return _validate(_handoff, value)
def validate_run_event(value): return _validate(_event, value)
def validate_run_result(value): return _validate(_result, value)
