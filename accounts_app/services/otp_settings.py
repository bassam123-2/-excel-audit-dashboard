"""Project-wide OTP timing (validity + resend cooldown)."""
from __future__ import annotations

from django.core.cache import cache

from accounts_app.models import (
    DEFAULT_OTP_TTL_SECONDS,
    MAX_OTP_TTL_SECONDS,
    MIN_OTP_TTL_SECONDS,
    ProjectSecuritySettings,
)

_OTP_TTL_CACHE_KEY = "project_otp_ttl_seconds"
_OTP_TTL_CACHE_TTL = 300


def _clamp_ttl(seconds: int) -> int:
    return max(MIN_OTP_TTL_SECONDS, min(MAX_OTP_TTL_SECONDS, int(seconds)))


def invalidate_otp_settings_cache() -> None:
    cache.delete(_OTP_TTL_CACHE_KEY)


def get_otp_ttl_seconds() -> int:
    """OTP validity and resend cooldown (seconds), configurable in admin."""
    cached = cache.get(_OTP_TTL_CACHE_KEY)
    if cached is not None:
        return _clamp_ttl(int(cached))

    try:
        ttl = ProjectSecuritySettings.load().otp_ttl_seconds
    except Exception:
        ttl = DEFAULT_OTP_TTL_SECONDS

    ttl = _clamp_ttl(ttl)
    cache.set(_OTP_TTL_CACHE_KEY, ttl, _OTP_TTL_CACHE_TTL)
    return ttl


def get_otp_resend_cooldown_seconds() -> int:
    """Resend cooldown matches OTP validity."""
    return get_otp_ttl_seconds()
