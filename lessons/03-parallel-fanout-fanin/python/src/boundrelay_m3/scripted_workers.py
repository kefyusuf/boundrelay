import asyncio
from copy import deepcopy
from .scenario import load_worker_fixture
from .types import WorkerExecutionError

class ScriptedWorkers:
    def __init__(self,spec,order_id):
        self.spec=spec;self.order_id=order_id;self.fixture=load_worker_fixture(spec.worker_fixture)
        self._gates={};self._entered=set();self._cursor=0;self._awaiting_ack=False;self._draining=False
    def _pump(self):
        if self._draining:
            for gate in self._gates.values():gate.set()
            return
        if self._cursor>=len(self.spec.completion_order) or self._awaiting_ack:return
        worker_id=self.spec.completion_order[self._cursor]
        if worker_id not in self._entered or (self._cursor==0 and self.spec.execution_mode=='parallel' and len(self._entered)<2):return
        self._awaiting_ack=True;self._gates[worker_id].set()
    async def read(self,worker_id,input):
        if self._draining or worker_id in self._entered or input.order_id!=self.order_id:raise ValueError('Invalid worker invocation')
        self._entered.add(worker_id);gate=asyncio.Event();self._gates[worker_id]=gate;self._pump();await gate.wait()
        instruction=self.fixture[worker_id]
        if instruction['operation']=='raise':raise WorkerExecutionError('Declared worker failure')
        return deepcopy(instruction['output'])
    def acknowledge_outcome(self,worker_id):
        if self._draining:return
        if not self._awaiting_ack or self.spec.completion_order[self._cursor]!=worker_id:raise ValueError('Invalid outcome acknowledgement')
        del self._gates[worker_id];self._cursor+=1;self._awaiting_ack=False;self._pump()
    def begin_drain(self):self._draining=True;self._pump()
