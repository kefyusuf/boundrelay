from .types import WORKER_IDS,WorkerDefinition
class FixedWorkerDirectory:
    def __init__(self,provider):self._read=provider.read
    def resolve(self,worker_id):
        if worker_id not in WORKER_IDS:return None
        async def handle(input):return await self._read(worker_id,input)
        return WorkerDefinition(worker_id,handle)
def create_worker_directory(provider):return FixedWorkerDirectory(provider)
