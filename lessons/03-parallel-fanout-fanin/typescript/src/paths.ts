import {fileURLToPath} from 'node:url';
export const ROOT=fileURLToPath(new URL('../../../../',import.meta.url)).replace(/[/\\]$/,'');
export const SCENARIO_PATH=ROOT+'/fixtures/scenarios/order-brief.yaml';
