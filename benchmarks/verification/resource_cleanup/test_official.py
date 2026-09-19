import sys,gc
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'candidate'))
from streaming.client import stream_rows
class R(list):
    def __init__(self,*a): super().__init__(*a); self.closes=0
    def close(self): self.closes+=1

def test_success_and_parse_failure_close():
    r=R(['1']); assert list(stream_rows(lambda:r))==[1] and r.closes==1
    bad=R(['x']);
    import pytest
    with pytest.raises(ValueError): list(stream_rows(lambda:bad))
    assert bad.closes==1

def test_early_close():
    r=R(['1','2']); g=stream_rows(lambda:r); assert next(g)==1; g.close(); gc.collect(); assert r.closes==1
