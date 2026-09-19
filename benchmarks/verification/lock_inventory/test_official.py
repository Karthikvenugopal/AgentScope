import sys,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'candidate'))
from inventory.store import Inventory

def test_no_oversell():
    for _ in range(10):
        s=Inventory({'x':1}); barrier=threading.Barrier(8); out=[]
        def run(): barrier.wait(); out.append(s.reserve('x'))
        ts=[threading.Thread(target=run) for _ in range(8)]; [t.start() for t in ts]; [t.join() for t in ts]
        assert sum(out)==1 and s.stock['x']==0

def test_invalid_quantity():
    import pytest
    with pytest.raises(ValueError): Inventory({'x':1}).reserve('x',0)
