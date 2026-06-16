"""
Centralized error tracking and logging for the Audit Dashboard.

Architecture
------------
* **Dedicated error log files** live under ``logs/errors/`` (never exposed via web).
* **Request context** (user, path, IP, request ID) is stored in a contextvar per
  request and attached automatically to every error record.
* **Unhandled exceptions** are captured by ``ErrorTrackingMiddleware`` and the
  ``got_request_exception`` Django signal (with deduplication).
* **Application code** can call :func:`log_error` or use :data:`error_logger` for
  caught exceptions that should still be tracked.

Sensitive values (passwords, tokens, API keys, etc.) are redacted before writing.

Example::

    from config.error_logging import log_error, error_logger

    try:
        process_upload(file)
    except ValueError as exc:
        log_error(exc, extra_context={"dashboard_id": dashboard.pk})
"""

from __future__ import annotations

from config.error_logging.tracker import error_logger, get_error_logger, log_error

__all__ = [
    "error_logger",
    "get_error_logger",
    "log_error",
]
