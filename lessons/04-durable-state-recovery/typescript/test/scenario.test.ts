import {expect,test} from 'vitest';
import {readFileSync} from 'node:fs';
import {parse} from 'yaml';
import {SCENARIO_PATH} from '../src/paths.js';
import {loadScenario,parseScenario,loadWorkerFixture} from '../src/scenario.js';
const raw=():any=>parse(readFileSync(SCENARIO_PATH,'utf8'));
test('loads_six_canonical_cases_with_recovery_metadata',()=>{
 const s=loadScenario();
 expect(s.scenario_id).toBe('order-brief-recovery');expect(s.cases).toHaveLength(6);
 const by=new Map(s.cases.map(c=>[c.case_id,c]));
 expect(by.get('parallel-crash-resume')!.controls).toEqual({crash_after:'payment-status'});
 expect(by.get('parallel-crash-resume-partial')!.controls).toEqual({crash_after:'delivery-status'});
 expect(by.get('parallel-cancel-resume')!.controls).toEqual({cancel_before:'delivery-status'});
 expect(by.get('parallel-replay-from-checkpoint')!.replay_from_step).toBe(1);
 expect(by.get('parallel-corrupt-state')!.tampered_state).toBe('flip_payment_outcome');
 expect(by.get('parallel-clean-complete')!.controls).toBeUndefined();
 for(const c of s.cases)expect(c.completion_order).toEqual(['order-details','payment-status','delivery-status']);
});
test('rejects_control_grammar_violations',()=>{
 const two=raw();two.cases[3].controls={crash_after:'order-details',cancel_before:'delivery-status'};
 expect(()=>parseScenario(two)).toThrow();
 const unknown=raw();unknown.cases[3].controls={crash_before:'delivery-status'};
 expect(()=>parseScenario(unknown)).toThrow('Unknown control field');
 const badTarget=raw();badTarget.cases[3].controls={crash_after:'unknown-worker'};
 expect(()=>parseScenario(badTarget)).toThrow('Invalid control target');
 const extra=raw();extra.cases[3].unexpected='field';
 expect(()=>parseScenario(extra)).toThrow('Invalid case fields');
});
test('rejects_infeasible_crash_and_cancel_targets',()=>{
 const first=raw();first.cases[0].controls={crash_after:'order-details'};
 expect(()=>parseScenario(first)).toThrow('Infeasible crash target');
 const badCancel=raw();badCancel.cases[0].controls={cancel_before:'payment-status'};
 expect(()=>parseScenario(badCancel)).toThrow('Infeasible cancel target');
});
test('rejects_replay_and_tamper_misuse',()=>{
 const withControl=raw();withControl.cases[4].controls={crash_after:'payment-status'};
 expect(()=>parseScenario(withControl)).toThrow();
 const badRange=raw();badRange.cases[4].replay_from_step=4;
 expect(()=>parseScenario(badRange)).toThrow('Invalid replay_from_step');
 const badTamper=raw();badTamper.cases[5].tampered_state='other';
 expect(()=>parseScenario(badTamper)).toThrow('Invalid tampered_state');
});
test('reject_worker_fixture_paths_escaping_the_reused_directory',()=>{
 expect(()=>loadWorkerFixture('fixtures/workers/order-brief/../../../fixtures/scenarios/order-brief-recovery.yaml')).toThrow('Worker fixture escapes root');
});
test('rejects_combined_replay_and_tamper_metadata',()=>{
 const both=raw();both.cases[4].replay_from_step=1;both.cases[4].tampered_state='flip_payment_outcome';
 expect(()=>parseScenario(both)).toThrow('Invalid control combination');
});

