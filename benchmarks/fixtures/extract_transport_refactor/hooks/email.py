import json
class EmailHooks:
    def __init__(self,http,token): self.http,self.token=http,token
    def send(self,url,payload): return self.http.post(url,body=json.dumps(payload,sort_keys=True),headers={'Authorization':f'Bearer {self.token}','Content-Type':'application/json'},timeout=5)
