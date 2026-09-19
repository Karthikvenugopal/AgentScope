import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'candidate'))
from hooks.email import EmailHooks
from hooks.audit import AuditHooks
class HTTP:
    def __init__(self): self.calls=[]
    def post(self,*a,**kw): self.calls.append((a,kw)); return 202
def test_both_clients_preserve_contract():
    http=HTTP(); assert EmailHooks(http,'t').send('/e',{'b':1,'a':2})==202; AuditHooks(http,'t').send('/a',{'b':1,'a':2})
    assert [c[1]['timeout'] for c in http.calls]==[5,10]
    for _,kw in http.calls:
        assert kw['body']=='{"a": 2, "b": 1}'
        assert kw['headers']=={'Authorization':'Bearer t','Content-Type':'application/json'}
def test_shared_abstraction_exists():
    from hooks.transport import Transport
    assert Transport
