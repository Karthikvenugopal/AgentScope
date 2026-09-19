import json
class AuditHooks:
    def __init__(self,http,token): self.http,self.token=http,token
    def send(self,url,payload): return self.http.post(url,body=json.dumps(payload),headers={'Authorization':f'Bearer {self.token}'},timeout=10)
