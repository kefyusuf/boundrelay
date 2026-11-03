import {expect,test} from 'vitest';
import {existsSync} from 'node:fs';
import {ROOT} from '../src/paths.js';
import {effectDigest,effectKey} from '../src/idempotency.js';
import type {EffectPayload} from '../src/types.js';
const PAYLOAD:EffectPayload={operation:'cancel-and-refund',order_id:'ORD-1001',refund_amount_cents:4200,currency:'EUR'};
test('repository_paths_resolve_real_fixtures',()=>expect(existsSync(ROOT+'/fixtures/scenarios/order-closure.yaml')).toBe(true));
test('m5_closed_contracts_are_present',()=>{
 expect(existsSync(ROOT+'/contracts/state/order-closure-run-state.schema.json')).toBe(true);
 expect(existsSync(ROOT+'/contracts/results/order-closure-result.schema.json')).toBe(true);
 expect(existsSync(ROOT+'/contracts/effects/order-closure-effect.schema.json')).toBe(true);
 expect(existsSync(ROOT+'/contracts/audit/order-closure-audit.schema.json')).toBe(true);
 expect(existsSync(ROOT+'/contracts/events/run-event.schema.json')).toBe(true);
});
test('effect_key_is_deterministic_and_stable',()=>{
 expect(effectKey(PAYLOAD)).toBe('cancel-and-refund:ORD-1001');
 expect(effectKey(PAYLOAD)).toBe(effectKey(structuredClone(PAYLOAD)));
 expect(effectDigest(PAYLOAD)).toMatch(/^[0-9a-f]{64}$/);
 expect(effectDigest(PAYLOAD)).toBe(effectDigest(structuredClone(PAYLOAD)));
 const other={...PAYLOAD,order_id:'ORD-1002'};
 expect(effectKey(other)).toBe('cancel-and-refund:ORD-1002');
 expect(effectKey(other)).not.toBe(effectKey(PAYLOAD));
 expect(effectDigest(other)).not.toBe(effectDigest(PAYLOAD));
});
test('effect_digest_binds_every_payload_field_and_key_never_reflects_amount',()=>{
 const amount={...PAYLOAD,refund_amount_cents:4300} as unknown as EffectPayload;
 expect(effectKey(amount)).toBe(effectKey(PAYLOAD));
 expect(effectDigest(amount)).not.toBe(effectDigest(PAYLOAD));
 const currency={...PAYLOAD,currency:'USD'} as unknown as EffectPayload;
 expect(effectDigest(currency)).not.toBe(effectDigest(PAYLOAD));
 expect(effectDigest(PAYLOAD)).toBe(effectDigest({order_id:'ORD-1001',currency:'EUR',refund_amount_cents:4200,operation:'cancel-and-refund'}));
});

