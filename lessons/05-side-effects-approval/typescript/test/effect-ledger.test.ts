import {expect,test} from 'vitest';
import {existsSync,mkdtempSync,readFileSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {EffectLedger} from '../src/effect-ledger.js';
import {effectDigest,effectKey} from '../src/idempotency.js';
import type {EffectPayload} from '../src/types.js';
const PAYLOAD:EffectPayload={operation:'cancel-and-refund',order_id:'ORD-1001',refund_amount_cents:4200,currency:'EUR'};
const KEY=effectKey(PAYLOAD);
const DIGEST=effectDigest(PAYLOAD);
const OUTCOME={refund_id:'RFL-1001',refunded_at:'2026-11-02T00:00:00Z'};
function freshRoot():string {return mkdtempSync(join(tmpdir(),'br-m5-ledger-'));}
test('ledger_enforces_once_per_key_with_deterministic_outcome',()=>{
 const root=freshRoot();const ledger=new EffectLedger(root);
 expect(ledger.path()).toBe(join(root,'effect-ledger.json'));
 expect(ledger.lookup(KEY)).toBeNull();
 const first=ledger.submit(KEY,DIGEST,PAYLOAD);
 expect(first).toEqual({status:'EFFECT_COMPLETED',outcome:OUTCOME,reason:null,duplicate:false});
 expect(ledger.records()).toEqual([{key:KEY,payload_digest:DIGEST,effect:{status:'EFFECT_COMPLETED',outcome:OUTCOME}}]);
 const before=readFileSync(ledger.path(),'utf8');
 const second=ledger.submit(KEY,DIGEST,PAYLOAD);
 expect(second).toEqual({status:'EFFECT_COMPLETED',outcome:OUTCOME,reason:null,duplicate:true});
 expect(ledger.records()).toHaveLength(1);
 expect(readFileSync(ledger.path(),'utf8')).toBe(before);
 expect(ledger.lookup(KEY)).toEqual({status:'EFFECT_COMPLETED',outcome:OUTCOME});
 rmSync(root,{recursive:true,force:true});
});
test('invalid_payload_is_rejected_once_and_adopted_on_duplicate',()=>{
 const bad={...PAYLOAD,refund_amount_cents:9999} as unknown as EffectPayload;
 const root=freshRoot();const ledger=new EffectLedger(root);
 const first=ledger.submit(KEY,effectDigest(bad),bad);
 expect(first.status).toBe('EFFECT_REJECTED');expect(first.outcome).toBeNull();
 expect(first.reason).toBe('INVALID_PAYLOAD');expect(first.duplicate).toBe(false);
 expect(ledger.records()).toHaveLength(1);
 expect(ledger.records()[0]!.effect).toEqual({status:'EFFECT_REJECTED',outcome:null,reason:'INVALID_PAYLOAD'});
 const again=ledger.submit(KEY,effectDigest(bad),bad);
 expect(again).toEqual({...first,duplicate:true});
 expect(ledger.records()).toHaveLength(1);
 expect(ledger.lookup(KEY)).toEqual({status:'EFFECT_REJECTED',outcome:null});
 rmSync(root,{recursive:true,force:true});
});
test('extra_field_payload_is_rejected',()=>{
 const root=freshRoot();const ledger=new EffectLedger(root);
 const bad={...PAYLOAD,memo:'x'} as unknown as EffectPayload;
 const result=ledger.submit(KEY,effectDigest(bad),bad);
 expect(result.status).toBe('EFFECT_REJECTED');expect(result.duplicate).toBe(false);
 rmSync(root,{recursive:true,force:true});
});
test('atomic_write_leaves_previous_ledger_loadable',()=>{
 const root=freshRoot();const ledger=new EffectLedger(root);
 ledger.submit(KEY,DIGEST,PAYLOAD);
 writeFileSync(ledger.path()+'.tmp','{"records": [');
 expect(ledger.lookup(KEY)!.status).toBe('EFFECT_COMPLETED');
 const reopened=new EffectLedger(root);
 expect(reopened.lookup(KEY)).toEqual(ledger.lookup(KEY));
 const other={...PAYLOAD,order_id:'ORD-1002'} as EffectPayload;
 reopened.submit(effectKey(other),effectDigest(other),other);
 expect(existsSync(ledger.path()+'.tmp')).toBe(false);
 rmSync(root,{recursive:true,force:true});
});
test('ledger_persists_across_instances_and_keys_stay_distinct',()=>{
 const root=freshRoot();
 new EffectLedger(root).submit(KEY,DIGEST,PAYLOAD);
 const ledger=new EffectLedger(root);
 expect(ledger.records()).toHaveLength(1);
 const other={...PAYLOAD,order_id:'ORD-1002'} as EffectPayload;
 const result=ledger.submit(effectKey(other),effectDigest(other),other);
 expect(result.duplicate).toBe(false);
 expect(ledger.records()).toHaveLength(2);
 expect(ledger.lookup(effectKey(other))!.status).toBe('EFFECT_COMPLETED');
 expect(ledger.lookup('cancel-and-refund:ORD-9999')).toBeNull();
 rmSync(root,{recursive:true,force:true});
});
test('corrupt_ledger_file_fails_closed',()=>{
 const root=freshRoot();new EffectLedger(root);
 writeFileSync(join(root,'effect-ledger.json'),'{"records": [');
 expect(()=>new EffectLedger(root).lookup(KEY)).toThrow();
 rmSync(root,{recursive:true,force:true});
});



