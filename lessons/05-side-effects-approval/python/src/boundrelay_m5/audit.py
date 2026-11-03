import json
from pathlib import Path
from .schemas import canonical_json,validate_audit_record

class AuditWriter:
    def __init__(self,state_dir):
        self.state_dir=Path(state_dir)
        self.state_dir.mkdir(parents=True,exist_ok=True)
    def path(self)->Path:
        return self.state_dir/'audit.jsonl'
    def append(self,record)->None:
        if not validate_audit_record(record):raise ValueError('Invalid audit record')
        with open(self.path(),'a',encoding='utf-8') as handle:
            handle.write(canonical_json(record)+'\n')
    def records(self)->list[dict[str,object]]:
        path=self.path()
        if not path.exists():return []
        return [json.loads(line) for line in path.read_text(encoding='utf-8').split('\n') if line.strip()]
