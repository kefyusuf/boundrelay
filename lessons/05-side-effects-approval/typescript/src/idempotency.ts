import {createHash} from 'node:crypto';
import {canonicalJson} from './schemas.js';
import type {EffectPayload} from './types.js';
export function effectDigest(payload:EffectPayload):string {
 return createHash('sha256').update(canonicalJson(payload),'utf8').digest('hex');
}
export function effectKey(payload:EffectPayload):string {
 return `${payload.operation}:${payload.order_id}`;
}
