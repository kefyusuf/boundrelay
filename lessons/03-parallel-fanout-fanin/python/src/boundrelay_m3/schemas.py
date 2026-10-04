from copy import deepcopy
import json
import math
from jsonschema import Draft202012Validator,FormatChecker
from .paths import ROOT
from .types import ValidationResult

def load_schema(relative):
    return Draft202012Validator(json.loads((ROOT/relative).read_text(encoding='utf-8')),format_checker=FormatChecker())
WORKER_VALIDATOR=load_schema('contracts/workers/order-brief-worker-result.schema.json')
RESULT_VALIDATOR=load_schema('contracts/results/order-brief-result.schema.json')
EVENT_VALIDATOR=load_schema('contracts/events/run-event.schema.json')

def finite_json(value,seen=None,depth=0):
    if depth>32:return False
    if value is None or type(value) in (str,bool):return True
    if type(value) is int:return -(2**53-1)<=value<=2**53-1
    if type(value) is float:return math.isfinite(value) and (not value.is_integer() or abs(value)<=2**53-1)
    if type(value) not in (dict,list,tuple):return False
    seen=set() if seen is None else seen
    marker=id(value)
    if marker in seen:return False
    seen.add(marker)
    try:
        if type(value) is dict:return all(type(k) is str and finite_json(v,seen,depth+1) for k,v in value.items())
        return all(finite_json(v,seen,depth+1) for v in value)
    finally:seen.remove(marker)

def validate_worker_output(worker_id,raw,order_id):
    if not finite_json(raw):return ValidationResult(False)
    candidate={'worker_id':worker_id,'status':'SUCCEEDED','output':raw,'failure_code':None}
    if not WORKER_VALIDATOR.is_valid(candidate) or raw['order_id']!=order_id:return ValidationResult(False)
    return ValidationResult(True,deepcopy(raw))

def validate_worker_outcome(raw,order_id):
    return finite_json(raw) and WORKER_VALIDATOR.is_valid(raw) and (raw['output'] is None or raw['output']['order_id']==order_id)

def validate_run_result(raw):
    # JSON uses lists; internal canonical tuples are converted before validation.
    return finite_json(raw) and RESULT_VALIDATOR.is_valid(raw)
