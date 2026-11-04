export const STEP_KINDS=['read','model_decision','tool_call','effect','handoff','route','synthesis'] as const;
export type AttributionRecord={step_name:string;latency_ms:number;cost_cents:number;attempts:number};
export type AttributionBlock={steps:AttributionRecord[];totals:{latency_ms:number;cost_cents:number;attempts:number}};
export type AttributionTables={latency_ms:Record<string,number>;price_table:Record<string,number>};
export function stepKind(stepName:string):string{
 if(stepName==='model')return 'model_decision';
 if(stepName.startsWith('tool.'))return 'tool_call';
 throw new Error(`Unknown attribution step: ${stepName}`);
}
export function buildAttribution(stepRecords:ReadonlyArray<readonly [string,number]>,priceTable:Record<string,number>,latencyTable:Record<string,number>):AttributionBlock{
 const steps:AttributionRecord[]=[];const totals={latency_ms:0,cost_cents:0,attempts:0};
 for(const [stepName,attempts] of stepRecords){
  if(!Number.isInteger(attempts)||attempts<1)throw new Error(`Invalid attribution attempts for ${stepName}`);
  if(!(stepName in latencyTable))throw new Error(`Unknown attribution step: ${stepName}`);
  const kind=stepKind(stepName);
  if(!(kind in priceTable))throw new Error(`Unknown attribution price kind: ${kind}`);
  const record:AttributionRecord={step_name:stepName,latency_ms:latencyTable[stepName]!*attempts,cost_cents:priceTable[kind]!*attempts,attempts};
  steps.push(record);totals.latency_ms+=record.latency_ms;totals.cost_cents+=record.cost_cents;totals.attempts+=attempts;
 }
 if(steps.length===0)throw new Error('Attribution requires at least one executed step');
 return {steps,totals};
}
