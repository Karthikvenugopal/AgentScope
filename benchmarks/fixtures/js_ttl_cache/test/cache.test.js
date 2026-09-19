import test from 'node:test'; import assert from 'node:assert/strict'; import {TTLCache} from '../src/cache.js';
test('stores value',()=>{const c=new TTLCache(()=>0); c.set('x','v',10); assert.equal(c.get('x'),'v');});
