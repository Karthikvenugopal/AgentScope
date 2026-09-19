import threading
class Inventory:
    def __init__(self, stock): self.stock=dict(stock); self._guard=threading.Lock(); self._locks={}
    def _lock(self,sku):
        with self._guard: return self._locks.setdefault(sku,threading.Lock())
    def reserve(self, sku, quantity=1):
        if quantity < 1: raise ValueError('quantity')
        with self._lock(sku):
            current=self.stock.get(sku,0)
            if current < quantity: return False
            self.stock[sku]=current-quantity; return True
