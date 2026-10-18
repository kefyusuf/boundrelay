from copy import deepcopy
from .types import WORKER_IDS,CanonicalOutcomes
from .schemas import validate_worker_outcome

def canonicalize_outcomes(raw,order_id)->CanonicalOutcomes:
    if type(raw) not in (list,tuple) or len(raw)!=3 or not all(validate_worker_outcome(o,order_id) for o in raw):raise ValueError('Incomplete or invalid fan in')
    if len({o['worker_id'] for o in raw})!=3:raise ValueError('Duplicate worker identity')
    return tuple(deepcopy(next(o for o in raw if o['worker_id']==i)) for i in WORKER_IDS)
