import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'candidate'; sys.path.insert(0,str(ROOT))
from orders.models import Order
from orders.repository import Repository
from orders.service import checkout

def test_failure_rolls_back():
    r=Repository(); o=Order(7)
    try: checkout(o,r,lambda _: (_ for _ in ()).throw(RuntimeError('declined')))
    except RuntimeError: pass
    assert (o.state,r.stock,r.states) == ('pending',1,{})

def test_no_stock_does_not_charge():
    called=[]; r=Repository(0)
    import pytest
    with pytest.raises(ValueError): checkout(Order(1),r,lambda x: called.append(x))
    assert called == []
