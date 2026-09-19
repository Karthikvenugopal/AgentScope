from orders.models import Order
from orders.repository import Repository
from orders.service import checkout

def test_success():
    r=Repository(); o=Order(1); checkout(o,r,lambda _: None)
    assert (o.state,r.stock,r.states[1]) == ('paid',0,'paid')
