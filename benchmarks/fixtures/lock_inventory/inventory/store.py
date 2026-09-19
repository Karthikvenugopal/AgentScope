import time
class Inventory:
    def __init__(self, stock): self.stock=dict(stock)
    def reserve(self, sku, quantity=1):
        current=self.stock.get(sku,0)
        if current < quantity: return False
        time.sleep(.002)
        self.stock[sku]=current-quantity
        return True
