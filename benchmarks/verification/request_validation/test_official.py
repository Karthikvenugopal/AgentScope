import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1] / 'candidate'
spec = importlib.util.spec_from_file_location('validation', ROOT / 'signup/validation.py')
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

@pytest.mark.parametrize('payload,field', [({}, 'email'), ({'email': 'x', 'name': 'Ada'}, 'email'), ({'email': 'a@b.co', 'name': ' '}, 'name'), ({'email': 'a@b.co', 'name': 'x'*81}, 'name')])
def test_rejects(payload, field):
    with pytest.raises(mod.ValidationError, match=field): mod.validate_signup(payload)

def test_normalizes_without_mutation():
    p = {'email': ' A@B.COM ', 'name': ' Ada '}
    assert mod.validate_signup(p) == {'email': 'a@b.com', 'name': 'Ada'}
    assert p['email'] == ' A@B.COM '
