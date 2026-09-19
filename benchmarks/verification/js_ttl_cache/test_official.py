import json, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'candidate'
def run(script):
    result=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,text=True,capture_output=True)
    assert result.returncode==0, result.stderr
def test_expiry_and_falsy_values():
    run("import {TTLCache} from './src/cache.js'; let n=5; const c=new TTLCache(()=>n); for (const [k,v] of [['z',0],['f',false],['e','']]) c.set(k,v,2); if(c.get('z')!==0||c.get('f')!==false||c.get('e')!=='') process.exit(2); n=7; if(c.get('z')!==undefined) process.exit(3)")
def test_negative_ttl_rejected():
    run("import {TTLCache} from './src/cache.js'; try { new TTLCache(()=>0).set('x',1,-1); process.exit(2) } catch(e) { if(!(e instanceof RangeError)) process.exit(3) }")
