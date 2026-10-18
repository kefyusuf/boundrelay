from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
import json
from .schemas import finite_json,EVENT_VALIDATOR
class TraceSink:
    def __init__(self,run_id,path):self.run_id=run_id;self.path=Path(path);self.events=[]
    def emit(self,type,data):
        if not finite_json(data):raise ValueError('Unsafe event data')
        event={'schema_version':'1.0','event_id':str(uuid4()),'run_id':self.run_id,'sequence':len(self.events)+1,'type':type,'timestamp':datetime.now(timezone.utc).isoformat(),'source':'python','data':deepcopy(data)}
        if not EVENT_VALIDATOR.is_valid(event):raise ValueError('Invalid event envelope')
        self.events.append(event)
    def flush(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.path.write_text(''.join(json.dumps(e,allow_nan=False,ensure_ascii=True)+'\n' for e in self.events),encoding='utf-8')
