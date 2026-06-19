"""UI theme resolution: session (anonymous), profile (authenticated)."""
from __future__ import annotations

DEFAULT_UI_THEME = "light"
UI_THEME_CHOICES = frozenset({"light", "dark"})


def normalize_ui_theme(value: str | None) -> str:
    if not value:
        return DEFAULT_UI_THEME
    theme = str(value).strip().lower()
    return theme if theme in UI_THEME_CHOICES else DEFAULT_UI_THEME


def get_user_preferred_theme(user) -> str:
    if not getattr(user, "is_authenticated", False):
        return DEFAULT_UI_THEME
    from accounts_app.models import UserProfile

    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        return DEFAULT_UI_THEME
    return normalize_ui_theme(profile.preferred_theme)


def resolve_ui_theme(request) -> str:
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return get_user_preferred_theme(user)

    session_theme = request.session.get("ui_theme")
    if session_theme:
        return normalize_ui_theme(session_theme)

    return DEFAULT_UI_THEME


def apply_ui_theme_to_request(request, theme: str | None = None) -> str:
    theme = normalize_ui_theme(theme or resolve_ui_theme(request))
    request.session["ui_theme"] = theme
    request.ui_theme = theme
    return theme


def persist_preferred_theme(user, theme: str) -> None:
    if not getattr(user, "is_authenticated", False):
        return
    from accounts_app.models import UserProfile

    theme = normalize_ui_theme(theme)
    profile, _created = UserProfile.objects.get_or_create(user=user)
    if profile.preferred_theme != theme:
        profile.preferred_theme = theme
        profile.save(update_fields=["preferred_theme"])


def sync_user_theme_after_login(request, user) -> str:
    theme = get_user_preferred_theme(user)
    return apply_ui_theme_to_request(request, theme)
