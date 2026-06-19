"""Custom password complexity validator for auth users."""
from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


# Punctuation/symbols only — excludes letters, digits, spaces, Arabic chars, etc.
SPECIAL_SYMBOL_RE = r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?`~]"


class PasswordComplexityValidator:
    """Require lowercase, uppercase, digit, and symbol in passwords."""

    def validate(self, password: str, user=None) -> None:
        errors: list[str] = []
        if not re.search(r"[a-z]", password):
            errors.append(_("Password must contain at least one lowercase letter."))
        if not re.search(r"[A-Z]", password):
            errors.append(_("Password must contain at least one uppercase letter."))
        if not re.search(r"\d", password):
            errors.append(_("Password must contain at least one digit."))
        if not re.search(SPECIAL_SYMBOL_RE, password):
            errors.append(
                _("Password must contain at least one special symbol (e.g. @ # $).")
            )
        if errors:
            raise ValidationError(errors)

    def get_help_text(self) -> str:
        return _(
            "Your password must contain at least one lowercase letter, "
            "one uppercase letter, one digit, and one symbol."
        )
