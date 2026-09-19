from profiles.cache import Cache
from profiles.service import ProfileService
def test_read_through():
    s={('a','u'):{'name':'A'}}; service=ProfileService(s,Cache())
    assert service.get('a','u')['name']=='A'
