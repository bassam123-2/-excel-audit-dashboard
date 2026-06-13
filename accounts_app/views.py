from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from urllib.parse import quote

from audit_app.company_access import (
    SESSION_ACTIVE_COMPANY_KEY,
    clear_active_company,
    get_active_company,
    set_active_company,
    user_companies,
    user_must_select_company,
)
from reports_app.dashboard_workflow import dashboard_url_belongs_to_company
from web_strings import get_ui


def login_view(request):
    if request.user.is_authenticated:
        if user_must_select_company(request.user) and not get_active_company(request):
            return redirect("select_company")
        return _redirect_after_login(request.user)

    lang = request.session.get("ui_lang", "ar")
    ui = get_ui(lang)

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            profile = getattr(user, "profile", None)
            if profile and profile.is_deleted:
                form.add_error(None, ui.get("login_err_deleted", "This account has been deactivated."))
            elif profile and profile.two_factor_enabled:
                from accounts_app.services.two_factor import initiate_two_factor

                request.session["pending_2fa_user_id"] = user.pk
                request.session["pending_2fa_next"] = (
                    request.POST.get("next") or request.GET.get("next") or ""
                )
                try:
                    initiate_two_factor(user, lang)
                except ValueError as exc:
                    request.session.pop("pending_2fa_user_id", None)
                    request.session.pop("pending_2fa_next", None)
                    if str(exc) == "smtp_not_configured":
                        form.add_error(None, ui.get("login_err_smtp", "Email verification is unavailable."))
                    elif str(exc) == "no_email_for_2fa":
                        form.add_error(None, ui.get("login_err_no_email", "No email address on this account."))
                    else:
                        form.add_error(None, ui.get("login_err_2fa_send", "Could not send verification code."))
                else:
                    return redirect("verify_2fa")
            else:
                login(request, user)
                return _finish_login(
                    request,
                    user,
                    request.POST.get("next") or request.GET.get("next") or "",
                )
    else:
        form = AuthenticationForm(request)

    return render(
        request,
        "accounts/login.html",
        {"form": form, "next": request.GET.get("next", "")},
    )


def verify_2fa_view(request):
    from django.contrib.auth import get_user_model

    from accounts_app.services.two_factor import clear_otp, verify_otp

    lang = request.session.get("ui_lang", "ar")
    ui = get_ui(lang)
    user_id = request.session.get("pending_2fa_user_id")
    if not user_id:
        return redirect("login")

    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id, is_active=True)
    except User.DoesNotExist:
        request.session.pop("pending_2fa_user_id", None)
        request.session.pop("pending_2fa_next", None)
        return redirect("login")

    error = None
    if request.method == "POST":
        code = request.POST.get("otp_code", "")
        if verify_otp(user.pk, code):
            request.session.pop("pending_2fa_user_id", None)
            next_url = request.session.pop("pending_2fa_next", "") or ""
            login(request, user)
            return _finish_login(request, user, next_url)
        error = ui.get("verify_2fa_invalid", "Invalid or expired code.")

    if request.method == "POST" and request.POST.get("action") == "resend":
        from accounts_app.services.two_factor import initiate_two_factor

        try:
            initiate_two_factor(user, lang)
            messages.success(request, ui.get("verify_2fa_resent", "A new code was sent."))
        except ValueError:
            error = ui.get("login_err_2fa_send", "Could not send verification code.")

    return render(
        request,
        "accounts/verify_2fa.html",
        {
            "error": error,
            "email_hint": _mask_email(user.email),
            "subtitle": ui.get("verify_2fa_subtitle", "").format(email=_mask_email(user.email)),
        },
    )


def logout_view(request):
    from accounts_app.services.two_factor import clear_otp

    pending = request.session.get("pending_2fa_user_id")
    if pending:
        clear_otp(int(pending))
    request.session.pop("pending_2fa_user_id", None)
    request.session.pop("pending_2fa_next", None)
    clear_active_company(request)
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
def select_company_view(request):
    companies = user_companies(request.user)
    lang = request.session.get("ui_lang", "ar")
    ui = get_ui(lang)

    if not companies.exists():
        messages.warning(request, ui.get("company_none_assigned", "No company access assigned."))
        return redirect("profile")

    if companies.count() == 1:
        set_active_company(request, companies.first().pk)
        return redirect("index")

    if request.method == "POST":
        raw_id = request.POST.get("company_id", "").strip()
        if raw_id.isdigit() and set_active_company(request, int(raw_id)):
            next_url = request.POST.get("next") or reverse("index")
            if not next_url.startswith("/") or next_url.startswith("//"):
                next_url = reverse("index")
            return redirect(next_url)
        messages.error(request, ui.get("company_switch_invalid", "Invalid company selection."))

    return render(
        request,
        "accounts/select_company.html",
        {"companies": companies},
    )


@login_required
@require_http_methods(["POST"])
def switch_company_view(request):
    lang = request.session.get("ui_lang", "ar")
    ui = get_ui(lang)
    raw_id = request.POST.get("company_id", "").strip()
    next_url = request.POST.get("next") or reverse("index")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = reverse("index")

    if raw_id.isdigit() and set_active_company(request, int(raw_id)):
        active = get_active_company(request)
        if not dashboard_url_belongs_to_company(next_url, active):
            next_url = reverse("dashboard_list")
            messages.info(
                request,
                ui.get(
                    "company_switch_left_dashboard",
                    "Switched company — returned to the dashboard list.",
                ),
            )
        else:
            messages.success(request, ui.get("company_switch_success", "Company switched."))
        return redirect(next_url)

    messages.error(request, ui.get("company_switch_invalid", "Invalid company selection."))
    return redirect(next_url)


@login_required
def profile_view(request):
    from accounts_app.models import UserProfile
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    lang = request.session.get("ui_lang", "ar")
    ui = get_ui(lang)

    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    force_password = request.GET.get("force_password") == "1"

    ctx: dict = {
        "pw_error": None,
        "pw_mismatch": None,
        "profile": profile,
        "force_password": force_password,
    }

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "change_password":
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
                    profile.password_changed_at = timezone.now()
                    profile.save(update_fields=["password_changed_at"])
                    update_session_auth_hash(request, request.user)
                    messages.success(request, ui["profile_pw_changed_ok"])
                    return redirect("profile")

    return render(request, "accounts/profile.html", ctx)


# ── Internal helpers ──────────────────────────────────────────────


def _mask_email(email: str) -> str:
    email = (email or "").strip()
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "***"
    else:
        masked_local = local[0] + "***" + local[-1]
    return f"{masked_local}@{domain}"


def _prepare_company_session_after_login(request, user) -> None:
    """Force company selection after login when the user belongs to multiple companies."""
    if user_must_select_company(user):
        clear_active_company(request)


def _finish_login(request, user, next_url: str = ""):
    """Complete login redirect, enforcing company selection when required."""
    _prepare_company_session_after_login(request, user)
    safe_next = next_url if next_url.startswith("/") and not next_url.startswith("//") else ""

    if user_must_select_company(user):
        url = reverse("select_company")
        if safe_next:
            url = f"{url}?next={quote(safe_next)}"
        return redirect(url)

    if safe_next:
        return redirect(safe_next)
    return _redirect_after_login(user)


def _redirect_after_login(user):
    from reports_app.dashboard_workflow import has_upload_perm, has_view_perm

    companies = user_companies(user)
    if companies.count() > 1:
        return redirect(reverse("select_company"))

    active = companies.first() if companies.count() == 1 else None
    if has_upload_perm(user, active):
        return redirect(reverse("index"))
    if has_view_perm(user, active):
        return redirect(reverse("dashboard_list"))
    if companies.exists():
        return redirect(reverse("select_company"))
    return redirect(reverse("profile"))
