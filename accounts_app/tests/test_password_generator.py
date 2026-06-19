"""Tests for generate_compliant_password."""
from __future__ import annotations

import re

import pytest
from django.contrib.auth.password_validation import validate_password

from accounts_app.password_validators import SPECIAL_SYMBOL_RE
from accounts_app.services.password_generator import generate_compliant_password


@pytest.mark.unit
def test_generate_compliant_password_length():
    password = generate_compliant_password(16)
    assert len(password) == 16


@pytest.mark.unit
def test_generate_compliant_password_passes_django_validators():
    password = generate_compliant_password()
    validate_password(password)


@pytest.mark.unit
def test_generate_compliant_password_has_required_classes():
    password = generate_compliant_password(20)
    assert re.search(r"[a-z]", password)
    assert re.search(r"[A-Z]", password)
    assert re.search(r"\d", password)
    assert re.search(SPECIAL_SYMBOL_RE, password)
