class Cache:
    def __init__(self): self.values={}
    def get(self,key): return self.values.get(key)
    def put(self,key,value): self.values[key]=dict(value)
    def delete(self,key): self.values.pop(key,None)
