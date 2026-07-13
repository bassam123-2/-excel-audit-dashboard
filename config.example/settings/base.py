"""Shared Django settings: apps, middleware, DB, auth, logging."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from config.error_logging.setup import build_logging_config
from config.error_logging.signals import connect_error_signals

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "unsafe-dev-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "audit_app.apps.AuditAppConfig",
    "accounts_app",
    "reports_app",
    "exports_app",
    "mail_app",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.RequestTrackingMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # LocaleMiddleware must come AFTER SessionMiddleware and BEFORE CommonMiddleware
    # so that Django can read _language from session and activate it per request.
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts_app.middleware.ProjectTimezoneMiddleware",
    "config.middleware.UserLanguageMiddleware",
    "config.middleware.UserThemeMiddleware",
    "accounts_app.middleware.PasswordExpiryMiddleware",
    "accounts_app.middleware.ActiveCompanyMiddleware",
    "config.middleware.RequestContextRefreshMiddleware",
    "config.middleware.ErrorTrackingMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "config.middleware.NoSearchIndexMiddleware",
    "reports_app.middleware.DashboardVersionHeaderMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "reports_app.context_processors.ui_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("DB_NAME", "excel_dashboard"),
        "USER": os.environ.get("DB_USER", "excel_dashboard_user"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "3306"),
        "OPTIONS": {"charset": "utf8mb4"},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
        )
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "accounts_app.password_validators.PasswordComplexityValidator"},
]

# ── Internationalization ──────────────────────────────────────────────
# English is the default language. Users can switch to Arabic via the
# language toggle; anonymous choices live in session, signed-in users in profile.
LANGUAGE_CODE = "en"
LANGUAGES = [
    ("ar", "العربية"),
    ("en", "English"),
]
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
LOCALE_PATHS = [BASE_DIR / "locale"]

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "assets"]

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

# Workflow notification emails are sent in a background thread (OTP stays synchronous).
EMAIL_DISPATCH_SYNC = os.environ.get("EMAIL_DISPATCH_SYNC", "").lower() in (
    "1",
    "true",
    "yes",
)

_redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/1").strip()
_redis_protocol = os.environ.get("REDIS_PROTOCOL", "").strip()
_redis_cache_options: dict = {}
if _redis_protocol in ("2", "3"):
    _redis_cache_options["protocol"] = int(_redis_protocol)

if _redis_url:
    _default_cache: dict[str, Any] = {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": _redis_url,
    }
    if _redis_cache_options:
        _default_cache["OPTIONS"] = _redis_cache_options
    CACHES = {"default": _default_cache}
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "excel-audit-dashboard",
        }
    }

# ── Centralized error tracking ────────────────────────────────────────
# Error logs are written to BASE_DIR/logs/errors/ (server-side only).
# Override ERROR_LOGGING_ENABLED in test settings to disable file output.
ERROR_LOGGING_ENABLED = (
    os.environ.get("ERROR_LOGGING_ENABLED", "true").lower() == "true"
)

# Default logging config (development/production override debug flag).
LOGGING = build_logging_config(
    BASE_DIR,
    enabled=ERROR_LOGGING_ENABLED,
    debug=DEBUG,
)

# Register global exception signal handlers once settings are loaded.
connect_error_signals()
