import test from 'node:test'; import assert from 'node:assert/strict'; import {Loader} from '../src/loader.js';
test('loads',async()=>{const l=new Loader(async ks=>new Map([[ks[0],1]])); assert.equal(await l.get('x'),1);});
