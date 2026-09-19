import re


class ValidationError(ValueError):
    pass


def validate_signup(payload: dict[str, object]) -> dict[str, str]:
    email = str(payload.get('email', '')).strip().lower()
    name = str(payload.get('name', '')).strip()
    if not email or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
        raise ValidationError('email')
    if not name or len(name) > 80:
        raise ValidationError('name')
    return {'email': email, 'name': name}
