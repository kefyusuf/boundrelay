from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import uuid4
from .schemas import canonical_state_body,state_digest,validate_run_state_document
from .types import WORKER_IDS,RunStateDocument,StateBinding,StateLoadError,WorkerId,WorkerOutcome

TERMINAL=('SUCCEEDED','FAILED')

class StateStore:
    def __init__(self,root,binding:StateBinding,queue,run_id:str|None=None):
        self.root=Path(root);self._binding=binding;self._run_id=run_id or str(uuid4())
        self._document:RunStateDocument={'state_schema_version':'1.0','run_id':self._run_id,'scenario_id':'order-brief-recovery','case_id':binding.case_id,'execution_mode':binding.execution_mode,'concurrency_limit':binding.concurrency_limit,'requested_order_id':binding.requested_order_id,'status':'RUNNING','steps':[{'worker_id':worker_id,'status':'PENDING','output':None,'failure_code':None} for worker_id in queue],'sequence_cursor':0,'digest':''}
        self.state_path().parent.mkdir(parents=True,exist_ok=True)
        self.snapshot_path(1).parent.mkdir(parents=True,exist_ok=True)
        self._flush()
    @classmethod
    def create(cls,root,binding:StateBinding,queue)->'StateStore':
        return cls(root,binding,queue)
    def state(self)->RunStateDocument:
        return deepcopy(self._document)
    def state_path(self)->Path:
        return self.root/self._run_id/'state.json'
    def snapshot_path(self,seq:int)->Path:
        return self.root/self._run_id/'checkpoints'/f'step-{seq}.json'
    def mark_running(self,worker_id:WorkerId)->None:
        self._step(worker_id)['status']='RUNNING';self._flush()
    def record_step_terminal(self,worker_id:WorkerId,outcome:WorkerOutcome)->None:
        step=self._step(worker_id)
        if outcome['status']=='SUCCEEDED':
            step['status']='SUCCEEDED';step['output']=deepcopy(outcome['output']);step['failure_code']=None
        else:
            step['status']='FAILED';step['output']=None;step['failure_code']=outcome['failure_code']
        self._flush(WORKER_IDS.index(worker_id)+1)
    def mark_cancelled_from(self,worker_id:WorkerId)->None:
        from_index=WORKER_IDS.index(worker_id)
        for step in self._document['steps']:
            if WORKER_IDS.index(step['worker_id'])>=from_index and step['status'] not in TERMINAL:step['status']='CANCELLED'
        self._flush()
    def mark_terminal(self,status,failure_code=None)->None:
        if status=='FAILED' and failure_code!='ALL_WORKERS_FAILED':raise ValueError('Invalid terminal failure code')
        self._document['status']=status;self._flush()

    def _step(self,worker_id:WorkerId):
        return self._document['steps'][WORKER_IDS.index(worker_id)]
    def _flush(self,snapshot_seq:int|None=None)->None:
        self._document['sequence_cursor']=sum(1 for step in self._document['steps'] if step['status'] in TERMINAL)
        self._document['digest']=state_digest(canonical_state_body(self._document))
        if not validate_run_state_document(self._document).valid:raise ValueError('Invalid run state document')
        content=json.dumps(self._document,sort_keys=True,separators=(',',':'),ensure_ascii=True)
        self._write_atomic(self.state_path(),content)
        if snapshot_seq is not None:self._write_atomic(self.snapshot_path(snapshot_seq),content)
    def _write_atomic(self,path:Path,content:str)->None:
        tmp=Path(str(path)+'.tmp')
        try:
            tmp.write_text(content,encoding='utf-8');os.replace(tmp,path)
        except BaseException:
            tmp.unlink(missing_ok=True);raise

def load_run_state(state_root,expected_binding:StateBinding)->dict[str,object]:
    root=Path(state_root);flat=root/'state.json'
    if flat.exists():paths=[flat]
    else:
        if not root.is_dir():raise ValueError(f'Expected exactly one run state document under {root}, found 0')
        paths=sorted(child/'state.json' for child in root.iterdir() if (child/'state.json').is_file())
    if len(paths)!=1:raise ValueError(f'Expected exactly one run state document under {root}, found {len(paths)}')
    path=paths[0]
    try:raw=json.loads(path.read_text(encoding='utf-8'))
    except ValueError:raise StateLoadError('TRUNCATED','run state document is not valid JSON') from None
    if type(raw) is not dict or raw.get('state_schema_version')!='1.0':raise StateLoadError('UNKNOWN_VERSION','missing or unsupported state_schema_version')
    validation=validate_run_state_document(raw)
    if not validation.valid:raise StateLoadError('SCHEMA_INVALID','run state document failed the closed schema')
    document:RunStateDocument=validation.value
    if document['digest']!=state_digest(canonical_state_body(document)):raise StateLoadError('DIGEST_MISMATCH',f"run_id={document['run_id']} case_id={document['case_id']}")
    if (document['case_id'],document['execution_mode'],document['requested_order_id'],document['concurrency_limit'])!=(expected_binding.case_id,expected_binding.execution_mode,expected_binding.requested_order_id,expected_binding.concurrency_limit):raise StateLoadError('BINDING_MISMATCH',f"run_id={document['run_id']} case_id={document['case_id']}")
    checkpoints=root/str(document['run_id'])/'checkpoints'
    for index,step in enumerate(document['steps']):
        if step['status'] in TERMINAL:_verify_snapshot(checkpoints/f'step-{index+1}.json',index+1,document['run_id'])
    return {'document':document,'restored_from':str(path)}

def _verify_snapshot(path:Path,seq:int,run_id:str)->None:
    def missing(detail:str)->StateLoadError:
        return StateLoadError('MISSING_SNAPSHOT',f'checkpoint step-{seq} for run_id={run_id}: {detail}')
    if not path.exists():raise missing('missing')
    try:snapshot=json.loads(path.read_text(encoding='utf-8'))
    except ValueError:raise missing('unreadable') from None
    if type(snapshot) is not dict or snapshot.get('state_schema_version')!='1.0':raise missing('invalid')
    validation=validate_run_state_document(snapshot)
    if not validation.valid or validation.value['digest']!=state_digest(canonical_state_body(validation.value)):raise missing('invalid')
