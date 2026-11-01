import {expect,test} from 'vitest';
import {existsSync} from 'node:fs';
import {ROOT} from '../src/paths.js';
test('repository_paths_resolve_real_fixtures',()=>expect(existsSync(ROOT+'/fixtures/scenarios/order-brief-recovery.yaml')).toBe(true));
test('m4_closed_contracts_are_present',()=>{
 expect(existsSync(ROOT+'/contracts/state/order-brief-run-state.schema.json')).toBe(true);
 expect(existsSync(ROOT+'/contracts/results/order-brief-recovery-result.schema.json')).toBe(true);
 expect(existsSync(ROOT+'/contracts/events/run-event.schema.json')).toBe(true);
});
