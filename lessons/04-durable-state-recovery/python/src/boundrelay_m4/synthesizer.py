from .collector import canonicalize_outcomes
from .types import Brief,CanonicalOutcomes

def synthesize_brief(order_id:str,outcomes:CanonicalOutcomes)->Brief:
    canonical=canonicalize_outcomes(outcomes,order_id)
    sections=[{'worker_id':outcome['worker_id'],'output':outcome['output']} for outcome in canonical if outcome['status']=='SUCCEEDED']
    if not sections:raise ValueError('Cannot synthesize without successful evidence')
    missing_workers=[outcome['worker_id'] for outcome in canonical if outcome['status']=='FAILED']
    return {'order_id':order_id,'sections':sections,'missing_workers':missing_workers,'complete':not missing_workers}
