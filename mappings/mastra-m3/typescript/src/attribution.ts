/** Deterministic attribution for the P5c mapping, mirroring the M6 rules.
 *
 * Per-step latency = fixture table x attempts; totals = sum of steps. The
 * same fixture tables as the canonical lessons, priced the same way.
 */
export const STEP_KINDS=['read','model_decision','tool_call','effect','handoff','route','synthesis'] as const;
export type AttributionRecord={step_name:string;latency_ms:number;cost_cents:number;attempts:number};
export type AttributionBlock={steps:AttributionRecord[];totals:{latency_ms:number;cost_cents:number;attempts:number}};
export type AttributionTables={latency_ms:Record<string,number>;price_table:Record<string,number>};
export function stepKind(stepName:string):string{
 if(stepName==='synthesize')return 'synthesis';
 if(stepName.startsWith('worker.'))return 'read';
 throw new Error(`Unknown attribution step: ${stepName}`);
}
export function buildAttribution(stepRecords:ReadonlyArray<readonly [string,number]>,tables:AttributionTables):AttributionBlock{
 const steps:AttributionRecord[]=[];const totals={latency_ms:0,cost_cents:0,attempts:0};
 for(const [stepName,attempts] of stepRecords){
  if(!Number.isInteger(attempts)||attempts<1)throw new Error(`Invalid attribution attempts for ${stepName}`);
  if(!(stepName in tables.latency_ms))throw new Error(`Unknown attribution step: ${stepName}`);
  const kind=stepKind(stepName);
  if(!(kind in tables.price_table))throw new Error(`Unknown attribution price kind: ${kind}`);
  const record:AttributionRecord={step_name:stepName,latency_ms:tables.latency_ms[stepName]!*attempts,cost_cents:tables.price_table[kind]!*attempts,attempts};
  steps.push(record);totals.latency_ms+=record.latency_ms;totals.cost_cents+=record.cost_cents;totals.attempts+=attempts;
 }
 if(steps.length===0)throw new Error('Attribution requires at least one executed step');
 return {steps,totals};
}
