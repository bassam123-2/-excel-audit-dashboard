"""
Public API for recording application errors.
"""

from __future__ import annotations

import logging
from typing import Any

from django.http import HttpRequest

from config.error_logging.context import (
    build_context_from_request,
    get_request_context,
    set_request_context,
)
from config.error_logging.sanitizer import sanitize_mapping

# Logger name used across the project for centralized error tracking.
ERROR_LOGGER_NAME = "app.errors"

_error_logger: logging.Logger | None = None


def get_error_logger() -> logging.Logger:
    """Return the shared error-tracking logger (lazy-initialized)."""
    global _error_logger
    if _error_logger is None:
        _error_logger = logging.getLogger(ERROR_LOGGER_NAME)
    return _error_logger


def _merge_context(
    request: HttpRequest | None,
    extra_context: dict[str, Any] | None,
) -> dict[str, Any]:
    merged: dict[str, Any] = dict(get_request_context())
    if request is not None:
        merged.update(build_context_from_request(request))
    if extra_context:
        merged["extra_debug_context"] = sanitize_mapping(extra_context)
    return merged


def log_error(
    exc: BaseException | str,
    *,
    request: HttpRequest | None = None,
    extra_context: dict[str, Any] | None = None,
    level: int = logging.ERROR,
    already_logged_attr: str = "_central_error_logged",
) -> None:
    """
    Record an application error with full diagnostic context.

    Parameters
    ----------
    exc:
        Exception instance or error message string.
    request:
        Optional Django request; merged into context when provided.
    extra_context:
        Arbitrary key/value pairs for debugging (sanitized before write).
    level:
        Logging level (defaults to ERROR).
    already_logged_attr:
        Request attribute used to prevent duplicate records for the same failure.
    """
    if request is not None and getattr(request, already_logged_attr, False):
        return

    context = _merge_context(request, extra_context)
    if request is not None:
        set_request_context(context)

    logger = get_error_logger()
    message = str(exc) if isinstance(exc, BaseException) else exc
    exc_info = (type(exc), exc, exc.__traceback__) if isinstance(exc, BaseException) else None

    record_kwargs: dict[str, Any] = {
        "extra": {
            "request_id": context.get("request_id"),
            "user_id": context.get("user_id"),
            "request_path": context.get("path"),
            "http_method": context.get("method"),
            "client_ip": context.get("client_ip"),
            "extra_debug_context": context.get("extra_debug_context", {}),
        },
    }
    if exc_info:
        record_kwargs["exc_info"] = exc_info

    logger.log(level, message, **record_kwargs)

    if request is not None:
        setattr(request, already_logged_attr, True)


# Convenience alias used by application modules.
error_logger = get_error_logger()
