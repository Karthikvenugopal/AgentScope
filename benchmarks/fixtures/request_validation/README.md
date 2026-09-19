# Signup service

Validation lives in `signup/validation.py`. Email and name must be strings.
Email is trimmed, lowercased, and must have a local part plus a dotted domain.
Name is trimmed, required, and limited to 80 characters. Validation errors name
the invalid field and the input mapping must not be mutated.
