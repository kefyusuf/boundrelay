from copy import deepcopy
import json
import math
from jsonschema import Draft202012Validator, FormatChecker
from .paths import EVENT_SCHEMA_PATH, RESULT_SCHEMA_PATH, HANDOFF_SCHEMA_PATH, ROUTE_SCHEMA_PATH
from .types import ValidationResult


def _validator(path):
    return Draft202012Validator(json.loads(path.read_text(encoding='utf-8')), format_checker=FormatChecker())


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


def _validate(schema, value):
    if not _finite(value):
        return ValidationResult(False, errors=('/ must be a finite, bounded JSON value',))
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
