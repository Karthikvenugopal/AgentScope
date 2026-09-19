import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'candidate'
def run(code):
    r=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,text=True,capture_output=True); assert r.returncode==0,r.stderr
def test_concurrent_deduplication():
    run("import {Loader} from './src/loader.js'; let calls=0; const l=new Loader(async ks=>{calls++; await new Promise(r=>setTimeout(r,20)); return new Map([[ks[0],42]])}); const [a,b]=await Promise.all([l.get('x'),l.get('x')]); if(a!==42||b!==42||calls!==1) process.exit(2)")
def test_failure_can_retry():
    run("import {Loader} from './src/loader.js'; let calls=0; const l=new Loader(async ks=>{calls++; if(calls===1) throw Error('x'); return new Map([[ks[0],7]])}); try{await l.get('x')}catch{}; await new Promise(r=>setTimeout(r,0)); if(await l.get('x')!==7||calls!==2) process.exit(2)")
