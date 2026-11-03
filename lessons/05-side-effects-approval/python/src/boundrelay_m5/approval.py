from .idempotency import effect_digest

class ApprovalGate:
    def __init__(self,metadata:dict[str,object]):
        self.metadata=metadata
    def decide(self,payload)->dict[str,object]:
        record={'operation':payload['operation'],'order_id':payload['order_id'],
                'payload_digest':effect_digest(payload),'decision':self.metadata['decision'],
                'approver':self.metadata['approver']}
        return {'decision':self.metadata['decision'],'record':record}

def require_approval(record,payload)->None:
    if (record['operation']!=payload['operation'] or record['order_id']!=payload['order_id']
            or record['payload_digest']!=effect_digest(payload)):
        raise ValueError('Approval binding mismatch')
    if record['decision']!='granted':
        raise ValueError('Approval not granted')
