"""Test overlay: in-memory SQLite for pytest."""

from .base import *  # noqa: F403,F401

ERROR_LOGGING_ENABLED = False
LOGGING = build_logging_config(BASE_DIR, enabled=False)  # noqa: F405

EMAIL_DISPATCH_SYNC = True

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "excel-audit-dashboard-test",
    }
}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "test_db.sqlite3",  # noqa: F405
    }
}
