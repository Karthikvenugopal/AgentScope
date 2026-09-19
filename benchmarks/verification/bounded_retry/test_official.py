import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'candidate'))
from delivery.errors import TransientError, PermanentError
from delivery.retry import deliver_with_retry

def test_bounded_backoff():
    calls=[]; delays=[]
    def send():
        calls.append(1)
        if len(calls)<3: raise TransientError()
        return 'ok'
    assert deliver_with_retry(send,delays.append,3,.25)=='ok'
    assert len(calls)==3 and delays==[.25,.5]

def test_permanent_not_retried():
    calls=[]
    import pytest
    with pytest.raises(PermanentError): deliver_with_retry(lambda:(calls.append(1) or (_ for _ in ()).throw(PermanentError())),lambda _:None)
    assert len(calls)==1
