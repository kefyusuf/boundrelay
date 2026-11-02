import {WORKER_IDS,type WorkerDirectory,type WorkerProvider} from './types.js';
export function createWorkerDirectory(provider:WorkerProvider):WorkerDirectory {
 return {resolve:id=>WORKER_IDS.includes(id)?{id,handle:input=>provider.read(id,input)}:undefined};
}
