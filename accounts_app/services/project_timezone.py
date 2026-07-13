"""Project-wide timezone (display and local timestamps)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones

from django.core.cache import cache
from django.utils import timezone

from accounts_app.models import DEFAULT_PROJECT_TIMEZONE, ProjectSecuritySettings

_TIMEZONE_CACHE_KEY = "project_timezone_name"
_TIMEZONE_CACHE_TTL = 300

_PRIORITY_TIMEZONES = (
    "UTC",
    "Asia/Riyadh",
    "Asia/Dubai",
    "Asia/Kuwait",
    "Asia/Bahrain",
    "Asia/Qatar",
    "Asia/Muscat",
    "Asia/Amman",
    "Asia/Beirut",
    "Asia/Baghdad",
    "Africa/Cairo",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "America/New_York",
    "America/Chicago",
    "America/Los_Angeles",
)


def invalidate_project_timezone_cache() -> None:
    cache.delete(_TIMEZONE_CACHE_KEY)


def _normalize_timezone_name(name: str) -> str:
    tz_name = str(name or "").strip() or DEFAULT_PROJECT_TIMEZONE
    if tz_name not in available_timezones():
        return DEFAULT_PROJECT_TIMEZONE
    return tz_name


def get_project_timezone_name() -> str:
    """Configured IANA timezone name for the whole application."""
    cached = cache.get(_TIMEZONE_CACHE_KEY)
    if cached is not None:
        return _normalize_timezone_name(str(cached))

    try:
        tz_name = ProjectSecuritySettings.load().timezone
    except Exception:
        tz_name = DEFAULT_PROJECT_TIMEZONE

    tz_name = _normalize_timezone_name(tz_name)
    cache.set(_TIMEZONE_CACHE_KEY, tz_name, _TIMEZONE_CACHE_TTL)
    return tz_name


def get_project_timezone() -> ZoneInfo:
    return ZoneInfo(get_project_timezone_name())


def activate_project_timezone() -> None:
    timezone.activate(get_project_timezone())


def project_localtime(value: datetime | None = None) -> datetime:
    if value is None:
        value = timezone.now()
    return timezone.localtime(value, get_project_timezone())


def project_local_now() -> datetime:
    return project_localtime(timezone.now())


def project_timezone_choices() -> list[tuple[str, str]]:
    all_tz = available_timezones()
    choices: list[tuple[str, str]] = []
    seen: set[str] = set()
    for tz_name in _PRIORITY_TIMEZONES:
        if tz_name in all_tz and tz_name not in seen:
            choices.append((tz_name, tz_name))
            seen.add(tz_name)
    for tz_name in sorted(all_tz):
        if tz_name not in seen:
            choices.append((tz_name, tz_name))
    return choices
