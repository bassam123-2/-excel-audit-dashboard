"""Optional email OTP: generate, verify, and send via SMTP."""
from __future__ import annotations

import hashlib
import secrets
from typing import Any

from django.core.cache import cache

OTP_TTL_SECONDS = 600
OTP_MAX_ATTEMPTS = 5
OTP_LENGTH = 6


def _cache_key(user_id: int) -> str:
    return f"2fa_otp:{user_id}"


def _hash_otp(user_id: int, code: str) -> str:
    return hashlib.sha256(f"{user_id}:{code}".encode()).hexdigest()


def generate_and_store_otp(user_id: int) -> str:
    code = "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))
    payload = {"hash": _hash_otp(user_id, code), "attempts": 0}
    cache.set(_cache_key(user_id), payload, OTP_TTL_SECONDS)
    return code


def verify_otp(user_id: int, code: str) -> bool:
    payload = cache.get(_cache_key(user_id))
    if not payload:
        return False
    attempts = int(payload.get("attempts", 0))
    if attempts >= OTP_MAX_ATTEMPTS:
        cache.delete(_cache_key(user_id))
        return False
    normalized = str(code or "").strip()
    if not normalized or len(normalized) != OTP_LENGTH or not normalized.isdigit():
        payload["attempts"] = attempts + 1
        cache.set(_cache_key(user_id), payload, OTP_TTL_SECONDS)
        return False
    if payload.get("hash") != _hash_otp(user_id, normalized):
        payload["attempts"] = attempts + 1
        cache.set(_cache_key(user_id), payload, OTP_TTL_SECONDS)
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


def initiate_two_factor(user, locale: str, *, base_url: str | None = None) -> None:
    from ai_excel_dashboard import load_smtp_config

    from accounts_app.services.email_branding import resolve_logo_url

    email = (user.email or "").strip()
    if not email:
        raise ValueError("no_email_for_2fa")
    cfg = load_smtp_config()
    if not cfg:
        raise ValueError("smtp_not_configured")
    code = generate_and_store_otp(user.pk)
    logo_url = resolve_logo_url(base_url=base_url, cfg=cfg)
    send_otp_email_smtp(cfg, to_addr=email, code=code, locale=locale, logo_url=logo_url)
