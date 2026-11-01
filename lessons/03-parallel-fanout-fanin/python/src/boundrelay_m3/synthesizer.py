from .collector import canonicalize_outcomes
from .types import CanonicalOutcomes,Brief

def synthesize_brief(order_id:str,outcomes:CanonicalOutcomes)->Brief:
    canonical=canonicalize_outcomes(outcomes,order_id)
    sections=[{'worker_id':o['worker_id'],'output':o['output']} for o in canonical if o['status']=='SUCCEEDED']
    if not sections:raise ValueError('Cannot synthesize without successful evidence')
    missing=[o['worker_id'] for o in canonical if o['status']=='FAILED']
    return {'order_id':order_id,'sections':sections,'missing_workers':missing,'complete':not missing}
