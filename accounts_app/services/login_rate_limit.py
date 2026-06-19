"""Rate limiting for concurrent login attempts per username."""
from __future__ import annotations

from django.core.cache import cache

INFLIGHT_TTL_SECONDS = 8
FAIL_WINDOW_SECONDS = 300
MAX_FAILED_ATTEMPTS = 10


def _normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def _inflight_key(username: str) -> str:
    return f"login_inflight:{_normalize_username(username)}"


def _fail_key(username: str, ip: str) -> str:
    return f"login_fail:{_normalize_username(username)}:{ip or 'unknown'}"


def acquire_login_lock(username: str) -> bool:
    """Return True when this login attempt may proceed."""
    if not _normalize_username(username):
        return True
    return cache.add(_inflight_key(username), 1, INFLIGHT_TTL_SECONDS)


def release_login_lock(username: str) -> None:
    if not _normalize_username(username):
        return
    cache.delete(_inflight_key(username))


def is_login_blocked(username: str, ip: str) -> bool:
    if not _normalize_username(username):
        return False
    try:
        attempts = cache.get(_fail_key(username, ip), 0)
    except TypeError:
        attempts = 0
    return int(attempts or 0) >= MAX_FAILED_ATTEMPTS


def record_failed_login(username: str, ip: str) -> None:
    if not _normalize_username(username):
        return
    key = _fail_key(username, ip)
    try:
        attempts = cache.get(key, 0) or 0
    except TypeError:
        attempts = 0
    cache.set(key, int(attempts) + 1, FAIL_WINDOW_SECONDS)


def clear_failed_logins(username: str, ip: str) -> None:
    if not _normalize_username(username):
        return
    cache.delete(_fail_key(username, ip))
