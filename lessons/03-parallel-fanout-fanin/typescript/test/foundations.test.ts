import {expect,test} from 'vitest';
import {ROOT} from '../src/paths.js';
import {existsSync} from 'node:fs';
test('repository_paths_resolve_real_fixtures',()=>expect(existsSync(ROOT+'/fixtures/scenarios/order-brief.yaml')).toBe(true));
