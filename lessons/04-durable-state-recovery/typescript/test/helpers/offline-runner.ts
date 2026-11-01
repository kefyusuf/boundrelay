// Placeholder harness; the real offline subprocess runner lands with the M4 runner task.
export type OfflineRunnerArgs=readonly string[];
export function offlineRunner(_args:OfflineRunnerArgs):Promise<number> {return Promise.resolve(0);}
