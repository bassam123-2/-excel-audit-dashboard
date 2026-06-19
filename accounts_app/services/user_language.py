"""UI language resolution: session (anonymous), profile (authenticated), cookies."""
from __future__ import annotations

from django.conf import settings
from django.utils import translation

from accounts_app.models import UserProfile

DEFAULT_UI_LANG = "en"
UI_LANG_CHOICES = frozenset({"ar", "en"})


def normalize_ui_lang(value: str | None) -> str:
    if not value:
        return DEFAULT_UI_LANG
    lang = str(value).strip().lower().split("-")[0]
    return lang if lang in UI_LANG_CHOICES else DEFAULT_UI_LANG


def get_user_preferred_language(user) -> str:
    if not getattr(user, "is_authenticated", False):
        return DEFAULT_UI_LANG
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        return DEFAULT_UI_LANG
    return normalize_ui_lang(profile.preferred_language)


def resolve_ui_lang(request) -> str:
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return get_user_preferred_language(user)

    session_lang = request.session.get("ui_lang")
    if session_lang:
        return normalize_ui_lang(session_lang)

    active = translation.get_language()
    if active:
        return normalize_ui_lang(active)

    return DEFAULT_UI_LANG


def apply_ui_lang_to_request(request, lang: str | None = None) -> str:
    lang = normalize_ui_lang(lang or resolve_ui_lang(request))
    request.session["ui_lang"] = lang
    translation.activate(lang)
    return lang


def persist_preferred_language(user, lang: str) -> None:
    if not getattr(user, "is_authenticated", False):
        return
    lang = normalize_ui_lang(lang)
    profile, _created = UserProfile.objects.get_or_create(user=user)
    if profile.preferred_language != lang:
        profile.preferred_language = lang
        profile.save(update_fields=["preferred_language"])


def sync_user_language_after_login(request, user) -> str:
    """Apply the user's saved profile language to session and translation."""
    lang = get_user_preferred_language(user)
    return apply_ui_lang_to_request(request, lang)


def set_language_cookie(response, lang: str) -> None:
    lang = normalize_ui_lang(lang)
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME,
        lang,
        max_age=settings.LANGUAGE_COOKIE_AGE,
        path=settings.LANGUAGE_COOKIE_PATH,
        domain=settings.LANGUAGE_COOKIE_DOMAIN,
        secure=settings.LANGUAGE_COOKIE_SECURE,
        httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
        samesite=settings.LANGUAGE_COOKIE_SAMESITE,
    )
