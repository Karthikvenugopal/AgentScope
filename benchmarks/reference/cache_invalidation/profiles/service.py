class ProfileService:
    def __init__(self, store, cache): self.store,self.cache=store,cache
    @staticmethod
    def _key(tenant,user): return f'{tenant}:{user}'
    def get(self, tenant, user):
        key=self._key(tenant,user); cached=self.cache.get(key)
        if cached is not None: return cached
        value=self.store[(tenant,user)]; self.cache.put(key,value); return dict(value)
    def update(self, tenant, user, value):
        self.store[(tenant,user)]=dict(value); self.cache.delete(self._key(tenant,user))
