"""
Django LOGGING configuration for centralized error tracking.

Error logs:  ``<BASE_DIR>/logs/errors/errors.log``  (50 MB × 3 files)
App logs:    ``<BASE_DIR>/logs/app/application.log`` (10 MB × 5 files)

Neither directory is web-accessible. Files are created on first write.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

# Rotation policy for dedicated error log files.
ERROR_LOG_MAX_BYTES = 50 * 1024 * 1024  # 50 MB
ERROR_LOG_BACKUP_COUNT = 2  # current + 2 backups = 3 files total

APP_LOG_MAX_BYTES = 10 * 1024 * 1024
APP_LOG_BACKUP_COUNT = 4


def get_error_log_dir(base_dir: Path) -> Path:
    return base_dir / "logs" / "errors"


def get_app_log_dir(base_dir: Path) -> Path:
    return base_dir / "logs" / "app"


def ensure_log_directories(base_dir: Path) -> tuple[Path, Path]:
    """Create log directories if missing (server-side only)."""
    error_dir = get_error_log_dir(base_dir)
    app_dir = get_app_log_dir(base_dir)
    error_dir.mkdir(parents=True, exist_ok=True)
    app_dir.mkdir(parents=True, exist_ok=True)
    return error_dir, app_dir


def build_logging_config(
    base_dir: Path,
    *,
    enabled: bool = True,
    debug: bool = False,
) -> dict[str, Any]:
    """
    Build the Django ``LOGGING`` dictionary.

    When *enabled* is False (e.g. in tests), error output is discarded via
    ``logging.NullHandler`` so tests stay isolated from the filesystem.
    """
    if not enabled:
        return {
            "version": 1,
            "disable_existing_loggers": False,
            "handlers": {
                "null": {"class": "logging.NullHandler"},
            },
            "loggers": {
                "app.errors": {
                    "handlers": ["null"],
                    "level": "CRITICAL",
                    "propagate": False,
                },
            },
        }

    error_dir, app_dir = ensure_log_directories(base_dir)

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_context": {
                "()": "config.error_logging.formatter.RequestContextFilter",
            },
        },
        "formatters": {
            "error_detail": {
                "()": "config.error_logging.formatter.StructuredErrorFormatter",
            },
            "app_standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "null": {
                "class": "logging.NullHandler",
            },
            "error_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": str(error_dir / "errors.log"),
                "maxBytes": ERROR_LOG_MAX_BYTES,
                "backupCount": ERROR_LOG_BACKUP_COUNT,
                "formatter": "error_detail",
                "filters": ["request_context"],
                "encoding": "utf-8",
            },
            "app_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": str(app_dir / "application.log"),
                "maxBytes": APP_LOG_MAX_BYTES,
                "backupCount": APP_LOG_BACKUP_COUNT,
                "formatter": "app_standard",
                "encoding": "utf-8",
            },
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "app_standard",
                "level": "DEBUG" if debug else "INFO",
            },
        },
        "loggers": {
            # Central error tracker — all modules should log errors here.
            "app.errors": {
                "handlers": ["error_file"],
                "level": "ERROR",
                "propagate": False,
            },
            # Suppress Django's default request error logger to avoid duplicate
            # entries; unhandled exceptions are tracked by app.errors instead.
            "django.request": {
                "handlers": ["null"],
                "level": "ERROR",
                "propagate": False,
            },
            # Domain application loggers (INFO+ to app log, ERROR also via log_error).
            "audit_app": {"handlers": ["app_file", "console"], "level": "INFO", "propagate": False},
            "accounts_app": {"handlers": ["app_file", "console"], "level": "INFO", "propagate": False},
            "reports_app": {"handlers": ["app_file", "console"], "level": "INFO", "propagate": False},
            "exports_app": {"handlers": ["app_file", "console"], "level": "INFO", "propagate": False},
            "mail_app": {"handlers": ["app_file", "console"], "level": "INFO", "propagate": False},
            "config": {"handlers": ["app_file", "console"], "level": "INFO", "propagate": False},
        },
        "root": {
            "handlers": ["console"],
            "level": "WARNING",
        },
    }


def configure_rotating_handler(
    handler: RotatingFileHandler,
    *,
    max_bytes: int = ERROR_LOG_MAX_BYTES,
    backup_count: int = ERROR_LOG_BACKUP_COUNT,
) -> RotatingFileHandler:
    """Apply rotation limits to a handler (used by tests/documentation)."""
    handler.maxBytes = max_bytes
    handler.backupCount = backup_count
    return handler
