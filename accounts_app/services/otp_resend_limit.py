"""Rate limits for OTP resend and verify-2fa brute-force protection."""
from __future__ import annotations

from django.core.cache import cache

OTP_RESEND_IP_WINDOW_SECONDS = 900
OTP_RESEND_IP_MAX = 5
VERIFY_FAIL_WINDOW_SECONDS = 300
VERIFY_FAIL_IP_MAX = 20


def _resend_ip_key(ip: str) -> str:
    return f"otp_resend_ip:{ip or 'unknown'}"


def _verify_fail_ip_key(ip: str) -> str:
    return f"verify_2fa_fail_ip:{ip or 'unknown'}"


def is_otp_resend_ip_blocked(ip: str) -> bool:
    try:
        count = int(cache.get(_resend_ip_key(ip), 0) or 0)
    except (TypeError, ValueError):
        count = 0
    return count >= OTP_RESEND_IP_MAX


def record_otp_resend_ip(ip: str) -> None:
    key = _resend_ip_key(ip)
    try:
        count = int(cache.get(key, 0) or 0)
    except (TypeError, ValueError):
        count = 0
    cache.set(key, count + 1, OTP_RESEND_IP_WINDOW_SECONDS)


def is_verify_2fa_ip_blocked(ip: str) -> bool:
    try:
        count = int(cache.get(_verify_fail_ip_key(ip), 0) or 0)
    except (TypeError, ValueError):
        count = 0
    return count >= VERIFY_FAIL_IP_MAX


def record_verify_2fa_failure(ip: str) -> None:
    key = _verify_fail_ip_key(ip)
    try:
        count = int(cache.get(key, 0) or 0)
    except (TypeError, ValueError):
        count = 0
    cache.set(key, count + 1, VERIFY_FAIL_WINDOW_SECONDS)


def clear_verify_2fa_failures(ip: str) -> None:
    cache.delete(_verify_fail_ip_key(ip))
