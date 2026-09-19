import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'candidate'))
from profiles.cache import Cache
from profiles.service import ProfileService

def test_tenant_isolation_and_invalidation():
    store={('a','u'):{'name':'A'},('b','u'):{'name':'B'}}; cache=Cache(); s=ProfileService(store,cache)
    assert s.get('a','u')['name']=='A' and s.get('b','u')['name']=='B'
    s.update('a','u',{'name':'AA'})
    assert s.get('a','u')['name']=='AA' and s.get('b','u')['name']=='B'

def test_returned_value_does_not_poison_cache():
    s=ProfileService({('a','u'):{'name':'A'}},Cache()); value=s.get('a','u'); value['name']='bad'
    assert s.get('a','u')['name']=='A'
