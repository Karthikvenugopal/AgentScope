class ValidationError(ValueError):
    pass


def validate_signup(payload: dict[str, object]) -> dict[str, str]:
    email = str(payload.get('email', '')).strip()
    name = str(payload.get('name', '')).strip()
    return {'email': email, 'name': name}
