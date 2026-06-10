"""
Global Django signal hooks for unhandled request exceptions.

Complements :class:`config.middleware.ErrorTrackingMiddleware` for cases where
middleware does not run (e.g. certain early failures). Duplicate records for the
same request are suppressed via ``request._central_error_logged``.
"""

from __future__ import annotations

import logging

from django.core.signals import got_request_exception

from config.error_logging.tracker import log_error

_connected = False


def _on_request_exception(sender, request, **kwargs) -> None:
    exc = kwargs.get("exc")
    if exc is None:
        return
    log_error(exc, request=request)


def connect_error_signals() -> None:
    """Register signal handlers once per process."""
    global _connected
    if _connected:
        return
    got_request_exception.connect(_on_request_exception, weak=False)
    _connected = True
    logging.getLogger(__name__).debug("Error tracking signals connected.")
