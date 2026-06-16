"""Cryptographically secure passwords that satisfy PasswordComplexityValidator."""
from __future__ import annotations

import secrets
import string

from django.contrib.auth.password_validation import validate_password

LOWER = string.ascii_lowercase
UPPER = string.ascii_uppercase
DIGITS = string.digits
SYMBOLS = "!@#$%^&*()_+-=[]{}"
ALL_CHARS = LOWER + UPPER + DIGITS + SYMBOLS


def generate_compliant_password(length: int = 16) -> str:
    """Return a random password with lower, upper, digit, and symbol."""
    if length < 12:
        raise ValueError("length must be at least 12")

    required = [
        secrets.choice(LOWER),
        secrets.choice(UPPER),
        secrets.choice(DIGITS),
        secrets.choice(SYMBOLS),
    ]
    remaining = [secrets.choice(ALL_CHARS) for _ in range(length - len(required))]
    chars = required + remaining
    secrets.SystemRandom().shuffle(chars)
    password = "".join(chars)
    validate_password(password)
    return password
