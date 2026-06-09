from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import redirect, render
from django.urls import reverse


def login_view(request):
    if request.user.is_authenticated:
        return _redirect_after_login(request.user)

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            next_url = request.POST.get("next") or request.GET.get("next") or ""
            if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return _redirect_after_login(user)
    else:
        form = AuthenticationForm(request)

    return render(
        request,
        "accounts/login.html",
        {"form": form, "next": request.GET.get("next", "")},
    )


def logout_view(request):
    logout(request)
    return redirect("login")


def switch_language(request):
    """
    Toggle (or set) the UI language between 'ar' and 'en'.

    Stores the choice in two places:
      • request.session["ui_lang"]    — our custom context processor key
      • LANGUAGE_COOKIE_NAME cookie   — LocaleMiddleware reads this for admin i18n
    """
    from django.conf import settings as _conf
    from django.utils import translation

    explicit = request.GET.get("lang") or request.POST.get("lang")
    if explicit in ("ar", "en"):
        new_lang = explicit
    else:
        current = (
            request.session.get("ui_lang")
            or translation.get_language()
            or "ar"
        )
        current = str(current).split("-")[0]
        new_lang = "en" if current == "ar" else "ar"

    request.session["ui_lang"] = new_lang
    translation.activate(new_lang)

    next_url = request.GET.get("next") or request.POST.get("next") or "/"
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"

    response = redirect(next_url)
    # Set Django's language cookie so LocaleMiddleware picks it up
    response.set_cookie(
        _conf.LANGUAGE_COOKIE_NAME,
        new_lang,
        max_age=_conf.LANGUAGE_COOKIE_AGE,
        path=_conf.LANGUAGE_COOKIE_PATH,
        domain=_conf.LANGUAGE_COOKIE_DOMAIN,
        secure=_conf.LANGUAGE_COOKIE_SECURE,
        httponly=_conf.LANGUAGE_COOKIE_HTTPONLY,
        samesite=_conf.LANGUAGE_COOKIE_SAMESITE,
    )
    return response


@login_required
def profile_view(request):
    from accounts_app.models import UserProfile
    from web_strings import get_ui

    lang = request.session.get("ui_lang", "ar")
    ui = get_ui(lang)

    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    ctx: dict = {
        "pw_error": None,
        "pw_mismatch": None,
        "profile": profile,
    }

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "change_password":
            from django.contrib.auth.password_validation import validate_password
            from django.core.exceptions import ValidationError

            old_pw = request.POST.get("old_password", "")
            new_pw1 = request.POST.get("new_password1", "")
            new_pw2 = request.POST.get("new_password2", "")

            if not request.user.check_password(old_pw):
                ctx["pw_error"] = ui["profile_pw_wrong"]
            elif new_pw1 != new_pw2:
                ctx["pw_mismatch"] = ui["profile_pw_mismatch"]
            else:
                try:
                    validate_password(new_pw1, request.user)
                except ValidationError as exc:
                    ctx["pw_mismatch"] = " ".join(exc.messages)
                else:
                    request.user.set_password(new_pw1)
                    request.user.save()
                    update_session_auth_hash(request, request.user)
                    messages.success(request, ui["profile_pw_changed_ok"])
                    return redirect("profile")

    return render(request, "accounts/profile.html", ctx)


# ── Internal helpers ──────────────────────────────────────────────


def _redirect_after_login(user):
    if user.is_staff or user.is_superuser:
        return redirect(reverse("index"))
    if user.has_perm("audit_app.can_upload_files"):
        return redirect(reverse("index"))
    if user.has_perm("audit_app.can_view_dashboards"):
        return redirect(reverse("dashboard_list"))
    return redirect(reverse("index"))
