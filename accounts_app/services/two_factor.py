"""Optional email OTP: generate, verify, and send via SMTP."""
from __future__ import annotations

import hashlib
import secrets
from typing import Any

from django.core.cache import cache
from django.utils import timezone

from accounts_app.models import DEFAULT_OTP_TTL_SECONDS
from accounts_app.services.otp_settings import (
    get_otp_resend_cooldown_seconds,
    get_otp_ttl_seconds,
)

# Backward-compatible defaults for tests and imports.
OTP_TTL_SECONDS = DEFAULT_OTP_TTL_SECONDS
OTP_RESEND_COOLDOWN_SECONDS = DEFAULT_OTP_TTL_SECONDS

OTP_MAX_ATTEMPTS = 5
OTP_LENGTH = 6


def _cache_key(user_id: int) -> str:
    return f"2fa_otp:{user_id}"


def _resend_cooldown_key(user_id: int) -> str:
    return f"2fa_otp_resend:{user_id}"


def get_resend_cooldown_remaining(user_id: int) -> int:
    sent_at = cache.get(_resend_cooldown_key(user_id))
    if sent_at is None:
        return 0
    try:
        elapsed = timezone.now().timestamp() - float(sent_at)
    except (TypeError, ValueError):
        return 0
    cooldown = get_otp_resend_cooldown_seconds()
    return max(0, int(cooldown - elapsed))


def record_otp_sent(user_id: int) -> None:
    cache.set(
        _resend_cooldown_key(user_id),
        timezone.now().timestamp(),
        get_otp_resend_cooldown_seconds(),
    )


def _hash_otp(user_id: int, code: str) -> str:
    return hashlib.sha256(f"{user_id}:{code}".encode()).hexdigest()


def generate_and_store_otp(user_id: int) -> str:
    code = "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))
    payload = {"hash": _hash_otp(user_id, code), "attempts": 0}
    ttl = get_otp_ttl_seconds()
    cache.set(_cache_key(user_id), payload, ttl)
    return code


def verify_otp(user_id: int, code: str) -> bool:
    payload = cache.get(_cache_key(user_id))
    if not payload:
        return False
    ttl = get_otp_ttl_seconds()
    attempts = int(payload.get("attempts", 0))
    if attempts >= OTP_MAX_ATTEMPTS:
        cache.delete(_cache_key(user_id))
        return False
    normalized = str(code or "").strip()
    if not normalized or len(normalized) != OTP_LENGTH or not normalized.isdigit():
        payload["attempts"] = attempts + 1
        cache.set(_cache_key(user_id), payload, ttl)
        return False
    if payload.get("hash") != _hash_otp(user_id, normalized):
        payload["attempts"] = attempts + 1
        cache.set(_cache_key(user_id), payload, ttl)
        return False
    cache.delete(_cache_key(user_id))
    return True


def clear_otp(user_id: int) -> None:
    cache.delete(_cache_key(user_id))


def send_otp_email_smtp(
    cfg: dict[str, Any],
    *,
    to_addr: str,
    code: str,
    locale: str,
    logo_url: str | None = None,
) -> None:
    from accounts_app.services.email_branding import send_branded_email_smtp
    from accounts_app.services.otp_email import build_otp_email_content

    to_addr = to_addr.strip()
    content = build_otp_email_content(code=code, locale=locale, logo_url=logo_url)
    send_branded_email_smtp(
        cfg,
        to_addr=to_addr,
        subject=content["subject"],
        plain=content["plain"],
        html=content["html"],
    )


def initiate_two_factor(user, locale: str, *, base_url: str | None = None, is_resend: bool = False) -> None:
    from ai_excel_dashboard import load_smtp_config

    from accounts_app.services.email_branding import resolve_logo_src_for_email

    if is_resend:
        remaining = get_resend_cooldown_remaining(user.pk)
        if remaining > 0:
            raise ValueError("resend_cooldown")

    email = (user.email or "").strip()
    if not email:
        raise ValueError("no_email_for_2fa")
    cfg = load_smtp_config()
    if not cfg:
        raise ValueError("smtp_not_configured")
    code = generate_and_store_otp(user.pk)
    logo_url = resolve_logo_src_for_email(base_url=base_url, cfg=cfg)
    send_otp_email_smtp(cfg, to_addr=email, code=code, locale=locale, logo_url=logo_url)
    record_otp_sent(user.pk)
