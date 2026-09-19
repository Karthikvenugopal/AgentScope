class Repository:
    def __init__(self, stock=1): self.stock=stock; self.states={}
    def save(self, order): self.states[order.id]=order.state
