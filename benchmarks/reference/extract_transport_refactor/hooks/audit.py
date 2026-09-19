from .transport import Transport
class AuditHooks:
    def __init__(self,http,token): self.transport=Transport(http,token)
    def send(self,url,payload): return self.transport.post(url,payload,10)
