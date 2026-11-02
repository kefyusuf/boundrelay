import {expect,test} from 'vitest';
import {existsSync,mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {AuditWriter} from '../src/audit.js';
import type {AuditRecord} from '../src/types.js';
const DIGEST='c'.repeat(64);
const approval:AuditRecord={kind:'approval',operation:'cancel-and-refund',order_id:'ORD-1001',payload_digest:DIGEST,decision:'granted',approver:'approver-primary'};
const effect:AuditRecord={kind:'effect',operation:'cancel-and-refund',order_id:'ORD-1001',idempotency_key:'cancel-and-refund:ORD-1001',effect_status:'EFFECT_COMPLETED',duplicate:false};
function freshRoot():string {return mkdtempSync(join(tmpdir(),'br-m5-audit-'));}
test('audit_is_append_only_and_preserves_order',()=>{
 const root=freshRoot();const writer=new AuditWriter(root);
 expect(writer.records()).toEqual([]);
 writer.append(approval);
 const afterFirst=readFileSync(writer.path(),'utf8');
 writer.append(effect);
 const afterSecond=readFileSync(writer.path(),'utf8');
 expect(afterSecond.startsWith(afterFirst)).toBe(true);
 expect(afterSecond.split('\n').filter(line=>line.trim()!=='')).toHaveLength(2);
 expect(writer.records()).toEqual([approval,effect]);
 const reopened=new AuditWriter(root);
 reopened.append({...approval,decision:'rejected'});
 expect(writer.records()).toHaveLength(3);
 expect(writer.records()[2]).toEqual({...approval,decision:'rejected'});
 rmSync(root,{recursive:true,force:true});
});
test('audit_rejects_invalid_records_without_writing_them',()=>{
 const root=freshRoot();const writer=new AuditWriter(root);
 const bad:[unknown,...unknown[]]=[ {...approval,decision:'approved'},
  {...approval,extra:1},{...approval,payload_digest:'zz'},{...approval,approver:''},
  {...effect,effect_status:'EFFECT_LANDED'},{...effect,duplicate:'no'},{...effect,payload_digest:DIGEST},
  {...approval,idempotency_key:'k'},{kind:'approval',operation:'cancel-and-refund',order_id:'ORD-1001',payload_digest:DIGEST,decision:'granted'}];
 for(const record of bad)expect(()=>writer.append(record as AuditRecord)).toThrow();
 expect(writer.records()).toEqual([]);
 expect(existsSync(writer.path())).toBe(false);
 rmSync(root,{recursive:true,force:true});
});

