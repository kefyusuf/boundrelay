import {expect,test} from 'vitest';
import {readFileSync} from 'node:fs';
import {parse} from 'yaml';
import {SCENARIO_PATH} from '../src/paths.js';
import {loadScenario,parseScenario,loadWorkerFixture} from '../src/scenario.js';
const raw=():any=>parse(readFileSync(SCENARIO_PATH,'utf8'));
test('loads_six_canonical_cases_with_approval_and_control_metadata',()=>{
 const s=loadScenario();
 expect(s.scenario_id).toBe('order-closure');expect(s.cases).toHaveLength(6);
 const by=new Map(s.cases.map(c=>[c.case_id,c]));
 expect(by.get('approval-granted-effect-once')!.approval).toEqual({decision:'granted',approver:'approver-primary'});
 expect(by.get('approval-rejected-no-effect')!.approval).toEqual({decision:'rejected',approver:'approver-primary'});
 expect(by.get('retry-before-submit')!.controls).toEqual({crash_before_submit:true});
 expect(by.get('crash-submit-window-resolved')!.controls).toEqual({crash_in_submit_window:true});
 expect(by.get('sink-unavailable-unknown')!.controls).toEqual({crash_in_submit_window:true,sink_unavailable:true});
 expect(by.get('duplicate-key-suppressed')!.duplicate_key).toBe(true);
 for(const id of ['approval-granted-effect-once','approval-rejected-no-effect'])
  expect(by.get(id)!.controls).toBeUndefined();
 for(const c of s.cases)expect(c.completion_order).toEqual(['order-details','payment-status','delivery-status']);
});
test('rejects_control_grammar_violations',()=>{
 const unknown=raw();unknown.cases[2].controls={crash_before:'order-details'};
 expect(()=>parseScenario(unknown)).toThrow('Unknown control field');
 const mixed=raw();mixed.cases[2].controls={crash_before_submit:true,crash_in_submit_window:true};
 expect(()=>parseScenario(mixed)).toThrow('Invalid control combination');
 const both=raw();both.cases[3].controls={crash_in_submit_window:true,sink_unavailable:true};
 expect(()=>parseScenario(both)).toThrow('Invalid control combination');
 const sinkAlone=raw();sinkAlone.cases[3].controls={sink_unavailable:true};
 expect(()=>parseScenario(sinkAlone)).toThrow('Invalid control combination');
 const wrongCase=raw();wrongCase.cases[0].controls={crash_before_submit:true};
 expect(()=>parseScenario(wrongCase)).toThrow('Invalid controls for case');
 const extra=raw();extra.cases[0].unexpected='field';
 expect(()=>parseScenario(extra)).toThrow('Invalid case fields');
 const falseFlag=raw();falseFlag.cases[2].controls={crash_before_submit:false};
 expect(()=>parseScenario(falseFlag)).toThrow('Invalid control value');
});
test('rejects_invalid_approval_blocks',()=>{
 const badDecision=raw();badDecision.cases[0].approval={decision:'approved',approver:'approver-primary'};
 expect(()=>parseScenario(badDecision)).toThrow('Invalid approval decision');
 const emptyApprover=raw();emptyApprover.cases[0].approval={decision:'granted',approver:''};
 expect(()=>parseScenario(emptyApprover)).toThrow('Invalid approver');
 const missing=raw();delete missing.cases[0].approval;
 expect(()=>parseScenario(missing)).toThrow('Invalid case fields');
 const extra=raw();extra.cases[0].approval={decision:'granted',approver:'a',reason:'why'};
 expect(()=>parseScenario(extra)).toThrow('Invalid approval block');
});
test('rejects_duplicate_key_misuse_and_fixture_escapes',()=>{
 const wrongCase=raw();wrongCase.cases[0].duplicate_key=true;
 expect(()=>parseScenario(wrongCase)).toThrow('Invalid duplicate_key');
 const falseFlag=raw();falseFlag.cases[5].duplicate_key=false;
 expect(()=>parseScenario(falseFlag)).toThrow('Invalid duplicate_key');
 expect(()=>loadWorkerFixture('fixtures/workers/order-brief/../../../fixtures/scenarios/order-closure.yaml')).toThrow('Worker fixture escapes root');
 expect(()=>parseScenario({schema_version:'2.0'})).toThrow();
});

test('attribution_table_is_optional_and_validated',()=>{
 parseScenario(raw());
 const missing=raw();delete missing.attribution;parseScenario(missing);
 const unknownKind=raw();unknownKind.attribution.price_table.malformed=1;expect(()=>parseScenario(unknownKind)).toThrow();
 const pricedRead=raw();pricedRead.attribution.price_table.read=1;expect(()=>parseScenario(pricedRead)).toThrow();
 const noLatency=raw();delete noLatency.attribution.latency_ms;expect(()=>parseScenario(noLatency)).toThrow();
});

