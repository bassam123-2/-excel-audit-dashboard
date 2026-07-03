"""Request tracking, UI language sync, and error logging middleware."""
from __future__ import annotations

import uuid

from config.error_logging.context import (
    build_context_from_request,
    clear_request_context,
    set_request_context,
)
from config.error_logging.tracker import log_error
from config.robots import ROBOTS_HTTP_HEADER_VALUE


class NoSearchIndexMiddleware:
    """Add X-Robots-Tag on every response so crawlers do not index the private app."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["X-Robots-Tag"] = ROBOTS_HTTP_HEADER_VALUE
        return response


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


class UserLanguageMiddleware:
    """
    Resolve UI language after authentication is known.

    • Anonymous users: session, then LocaleMiddleware/cookie, then English default.
    • Authenticated users: profile preferred_language (persisted when they switch).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from accounts_app.services.user_language import (
            apply_ui_lang_to_request,
            resolve_ui_lang,
            set_language_cookie,
        )

        lang = resolve_ui_lang(request)
        apply_ui_lang_to_request(request, lang)
        response = self.get_response(request)
        set_language_cookie(response, lang)
        return response


class UserThemeMiddleware:
    """
    Resolve UI theme after authentication is known.

    • Anonymous users: session, default light.
    • Authenticated users: profile preferred_theme (default light).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from accounts_app.services.user_theme import (
            apply_ui_theme_to_request,
            resolve_ui_theme,
        )

        apply_ui_theme_to_request(request, resolve_ui_theme(request))
        return self.get_response(request)
