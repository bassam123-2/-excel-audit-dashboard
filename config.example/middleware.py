"""Request tracking, UI language sync, and error logging middleware."""
from __future__ import annotations

import uuid

from django.utils import translation

from config.error_logging.context import (
    build_context_from_request,
    clear_request_context,
    set_request_context,
)
from config.error_logging.tracker import log_error


class RequestTrackingMiddleware:
    """
    Assign a unique request ID and store request metadata for error logging.

    Runs early so downstream middleware, views, and the error tracker share the
    same correlation ID and context.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = request.META.get("HTTP_X_REQUEST_ID") or str(uuid.uuid4())
        set_request_context(build_context_from_request(request))
        try:
            response = self.get_response(request)
        finally:
            clear_request_context()
        response["X-Request-ID"] = request.request_id
        return response


class RequestContextRefreshMiddleware:
    """
    Refresh request context after AuthenticationMiddleware sets ``request.user``.

    Ensures error records include the authenticated user ID when available.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        set_request_context(build_context_from_request(request))
        return self.get_response(request)


class ErrorTrackingMiddleware:
    """
    Capture unhandled exceptions during request processing.

    Logs full diagnostic context to the dedicated error log file, then returns
    ``None`` so Django continues its normal error handling (500 page / DEBUG trace).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        log_error(exception, request=request)
        return None


class UiLanguageSyncMiddleware:
    """
    After LocaleMiddleware activates the language (cookie / Accept-Language),
    mirror it into session['ui_lang'] so admin and main site stay in sync.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        active = (translation.get_language() or "ar").split("-")[0]
        if active in ("ar", "en"):
            request.session["ui_lang"] = active
        return self.get_response(request)
