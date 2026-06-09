from __future__ import annotations

from django.utils import translation


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
