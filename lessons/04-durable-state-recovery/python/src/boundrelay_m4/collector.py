from copy import deepcopy
from .types import WORKER_IDS,CanonicalOutcomes
from .schemas import validate_worker_outcome

def canonicalize_outcomes(raw,order_id:str)->CanonicalOutcomes:
    if len(raw)!=3 or not all(validate_worker_outcome(outcome,order_id) for outcome in raw):raise ValueError('Incomplete or invalid fan in')
    if len({outcome['worker_id'] for outcome in raw})!=3:raise ValueError('Duplicate worker identity')
    return tuple(deepcopy(next(outcome for outcome in raw if outcome['worker_id']==worker_id)) for worker_id in WORKER_IDS)
