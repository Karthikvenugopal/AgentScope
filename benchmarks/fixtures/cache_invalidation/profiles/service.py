class ProfileService:
    def __init__(self, store, cache): self.store,self.cache=store,cache
    def get(self, tenant, user):
        key=user
        cached=self.cache.get(key)
        if cached is not None: return cached
        value=self.store[(tenant,user)]; self.cache.put(key,value); return value
    def update(self, tenant, user, value):
        self.store[(tenant,user)]=dict(value)
