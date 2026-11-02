import hashlib
from .schemas import canonical_json

def effect_digest(payload)->str:
    return hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()

def effect_key(payload)->str:
    return f"{payload['operation']}:{payload['order_id']}"
