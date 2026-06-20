"""One-time password-set links for admin-provisioned accounts."""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from accounts_app.models import PASSWORD_SET_TOKEN_TTL_HOURS, PasswordSetToken, UserProfile

User = get_user_model()


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_password_set_token(user: User) -> str:
    """Create a single-use token; invalidates previous unused tokens for this user."""
    PasswordSetToken.objects.filter(user=user, used_at__isnull=True).delete()
    raw = secrets.token_urlsafe(32)
    PasswordSetToken.objects.create(
        user=user,
        token_hash=_hash_token(raw),
        expires_at=timezone.now() + timedelta(hours=PASSWORD_SET_TOKEN_TTL_HOURS),
    )
    return raw


def get_valid_token(raw_token: str) -> PasswordSetToken | None:
    raw = str(raw_token or "").strip()
    if not raw:
        return None
    token = (
        PasswordSetToken.objects.select_related("user")
        .filter(token_hash=_hash_token(raw), used_at__isnull=True)
        .first()
    )
    if token is None or not token.is_valid:
        return None
    if not token.user.is_active:
        return None
    profile = getattr(token.user, "profile", None)
    if profile and profile.is_deleted:
        return None
    return token


def build_set_password_url(raw_token: str, *, base_url: str) -> str:
    from accounts_app.services.email_branding import require_secure_email_base_url

    site = require_secure_email_base_url(base_url)
    path = reverse("set_password", kwargs={"token": raw_token})
    return f"{site}{path}"


def set_password_with_token(*, token: PasswordSetToken, new_password: str) -> None:
    user = token.user
    user.set_password(new_password)
    user.save(update_fields=["password"])

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.password_changed_at = timezone.now()
    profile.must_change_password_on_login = False
    profile.save(
        update_fields=["password_changed_at", "must_change_password_on_login"]
    )

    token.used_at = timezone.now()
    token.save(update_fields=["used_at"])
