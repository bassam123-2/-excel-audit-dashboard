"""
Per-request context for error records.

Uses ``contextvars`` so context propagates correctly across threads and async
tasks without relying on global state.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from django.http import HttpRequest

_request_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "error_logging_request_context",
    default=None,
)


def get_client_ip(request: HttpRequest) -> str | None:
    """Resolve the client IP, honoring common reverse-proxy headers."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.META.get("HTTP_X_REAL_IP")
    if real_ip:
        return real_ip.strip()
    return request.META.get("REMOTE_ADDR")


def build_context_from_request(request: HttpRequest) -> dict[str, Any]:
    """Collect request metadata used in error log entries."""
    user = getattr(request, "user", None)
    user_id = None
    if user is not None and getattr(user, "is_authenticated", False):
        user_id = user.pk

    return {
        "request_id": getattr(request, "request_id", None),
        "user_id": user_id,
        "path": request.path,
        "method": request.method,
        "client_ip": get_client_ip(request),
        "query_string": request.META.get("QUERY_STRING") or "",
        "content_type": request.META.get("CONTENT_TYPE") or "",
        "user_agent": request.META.get("HTTP_USER_AGENT") or "",
        "referer": request.META.get("HTTP_REFERER") or "",
    }


def set_request_context(context: dict[str, Any]) -> None:
    """Store context for the current execution context (request/worker)."""
    _request_context.set(context)


def get_request_context() -> dict[str, Any]:
    """Return the active request context, or an empty dict."""
    return _request_context.get() or {}


def clear_request_context() -> None:
    """Remove request context at the end of a request."""
    _request_context.set(None)
