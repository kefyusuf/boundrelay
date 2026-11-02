import json
import os
from copy import deepcopy
from pathlib import Path
from .schemas import validate_effect_payload,validate_effect_record

REFUND_ID='RFL-1001'
REFUNDED_AT='2026-11-02T00:00:00Z'

def _result(effect,duplicate:bool)->dict[str,object]:
    if effect['status']=='EFFECT_COMPLETED':
        return {'status':'EFFECT_COMPLETED','outcome':effect['outcome'],'reason':None,'duplicate':duplicate}
    return {'status':'EFFECT_REJECTED','outcome':None,'reason':'INVALID_PAYLOAD','duplicate':duplicate}

class EffectLedger:
    def __init__(self,state_dir):
        self.state_dir=Path(state_dir)
        self.state_dir.mkdir(parents=True,exist_ok=True)
    def path(self)->Path:
        return self.state_dir/'effect-ledger.json'
    def _load(self)->dict[str,object]:
        path=self.path()
        if not path.exists():return {'records':[]}
        try:raw=json.loads(path.read_text(encoding='utf-8'))
        except ValueError:raise ValueError('Effect ledger is not valid JSON') from None
        if type(raw) is not dict or type(raw.get('records')) is not list or not all(validate_effect_record(record).valid for record in raw['records']):
            raise ValueError('Effect ledger failed the closed schema')
        return raw
    def _write_atomic(self,content:str)->None:
        tmp=Path(str(self.path())+'.tmp')
        try:
            tmp.write_text(content,encoding='utf-8');os.replace(tmp,self.path())
        except BaseException:
            tmp.unlink(missing_ok=True);raise
    def submit(self,key:str,digest:str,payload)->dict[str,object]:
        data=self._load()
        for record in data['records']:
            if record['key']==key:return _result(record['effect'],True)
        effect={'status':'EFFECT_COMPLETED','outcome':{'refund_id':REFUND_ID,'refunded_at':REFUNDED_AT}} if validate_effect_payload(payload).valid else {'status':'EFFECT_REJECTED','outcome':None,'reason':'INVALID_PAYLOAD'}
        record={'key':key,'payload_digest':digest,'effect':effect}
        self._write_atomic(json.dumps({**data,'records':[*data['records'],record]},sort_keys=True,separators=(',',':'),ensure_ascii=True))
        return _result(effect,False)
    def lookup(self,key:str)->dict[str,object]|None:
        for record in self._load()['records']:
            if record['key']==key:
                effect=record['effect']
                return {'status':effect['status'],'outcome':effect['outcome']}
        return None
    def records(self)->list[dict[str,object]]:
        return deepcopy(self._load()['records'])
