import pytest
from signup import ValidationError, validate_signup


def test_valid_signup():
    assert validate_signup({'email': ' A@B.COM ', 'name': ' Ada '}) == {'email': 'a@b.com', 'name': 'Ada'}


def test_missing_email():
    with pytest.raises(ValidationError):
        validate_signup({'name': 'Ada'})
