from inventory.store import Inventory
def test_single(): s=Inventory({'x':1}); assert s.reserve('x') and not s.reserve('x')
