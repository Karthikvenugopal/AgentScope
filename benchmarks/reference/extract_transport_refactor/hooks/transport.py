import json
class Transport:
    def __init__(self,http,token): self.http,self.token=http,token
    def post(self,url,payload,timeout): return self.http.post(url,body=json.dumps(payload,sort_keys=True),headers={'Authorization':f'Bearer {self.token}','Content-Type':'application/json'},timeout=timeout)
