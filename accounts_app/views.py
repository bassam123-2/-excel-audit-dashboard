"""Authentication views: login, 2FA, profile, password expiry, company selection."""
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
    active_companies_exist,
    clear_active_company,
    get_active_company,
    set_active_company,
    user_can_manage_companies,
    user_companies,
    user_must_select_company,
)
from accounts_app.navigation import resolve_default_home
from accounts_app.services.user_language import (
    DEFAULT_UI_LANG,
    apply_ui_lang_to_request,
    persist_preferred_language,
    resolve_ui_lang,
    set_language_cookie,
    sync_user_language_after_login,
)
from accounts_app.services.user_theme import (
    apply_ui_theme_to_request,
    persist_preferred_theme,
    resolve_ui_theme,
    sync_user_theme_after_login,
)
from reports_app.dashboard_workflow import dashboard_url_belongs_to_company
from web_strings import get_ui


def _safe_next_url(raw: str) -> str:
    """Return a same-site relative path suitable for post-login redirect."""
    value = (raw or "").strip()
    if value.startswith("/") and not value.startswith("//"):
        return value
    return ""


def _login_redirect_with_next(next_url: str):
    from django.urls import reverse

    login_url = reverse("login")
    safe = _safe_next_url(next_url)
    if safe:
        return redirect(f"{login_url}?next={quote(safe)}")
    return redirect(login_url)


def login_view(request):
    if request.user.is_authenticated:
        safe_next = _safe_next_url(request.GET.get("next") or request.POST.get("next") or "")
        if safe_next:
            return _finish_login(request, request.user, safe_next)
        if not active_companies_exist():
            return redirect("setup_required")
        if user_must_select_company(request.user) and not get_active_company(request):
            return redirect("select_company")
        return redirect(resolve_default_home(request.user, request))

    lang = request.session.get("ui_lang", DEFAULT_UI_LANG)
    ui = get_ui(lang)
    next_url = _safe_next_url(request.GET.get("next") or "")

    if request.method == "POST":
        from accounts_app.services.login_rate_limit import (
            acquire_login_lock,
            clear_failed_logins,
            is_login_blocked,
            record_failed_login,
            release_login_lock,
        )

        next_url = _safe_next_url(request.POST.get("next") or request.GET.get("next") or "")
        username = (request.POST.get("username") or "").strip()
        client_ip = request.META.get("REMOTE_ADDR", "")

        if is_login_blocked(username, client_ip):
            form = AuthenticationForm(request, data=request.POST)
            form.add_error(None, ui.get("login_err_rate_limit", "Too many attempts. Try again later."))
        elif not acquire_login_lock(username):
            form = AuthenticationForm(request, data=request.POST)
            form.add_error(None, ui.get("login_err_rate_limit", "A sign-in request is already in progress."))
        else:
            try:
                form = AuthenticationForm(request, data=request.POST)
                if form.is_valid():
                    user = form.get_user()
                    profile = getattr(user, "profile", None)
                    if profile and profile.is_deleted:
                        form.add_error(None, ui.get("login_err_deleted", "This account has been deactivated."))
                        record_failed_login(username, client_ip)
                    elif profile and profile.two_factor_enabled:
                        from accounts_app.services.two_factor import initiate_two_factor

                        request.session["pending_2fa_user_id"] = user.pk
                        request.session["pending_2fa_next"] = next_url
                        try:
                            initiate_two_factor(
                                user,
                                lang,
                                base_url=request.build_absolute_uri("/"),
                            )
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
                            clear_failed_logins(username, client_ip)
                            return redirect("verify_2fa")
                    else:
                        clear_failed_logins(username, client_ip)
                        login(request, user)
                        sync_user_language_after_login(request, user)
                        sync_user_theme_after_login(request, user)
                        return _finish_login(request, user, next_url)
                else:
                    record_failed_login(username, client_ip)
            finally:
                release_login_lock(username)
    else:
        form = AuthenticationForm(request)

    session_expired_msg = ""
    if request.GET.get("session_expired") == "1":
        session_expired_msg = ui.get(
            "login_session_expired",
            "Your session ended after one hour of inactivity. Please sign in again.",
        )

    return render(
        request,
        "accounts/login.html",
        {"form": form, "next": next_url, "session_expired_msg": session_expired_msg},
    )


def verify_2fa_view(request):
    from django.contrib.auth import get_user_model

    from accounts_app.services.otp_resend_limit import (
        is_otp_resend_ip_blocked,
        is_verify_2fa_ip_blocked,
        record_otp_resend_ip,
        record_verify_2fa_failure,
        clear_verify_2fa_failures,
    )
    from accounts_app.services.two_factor import (
        clear_otp,
        get_resend_cooldown_remaining,
        verify_otp,
    )

    lang = request.session.get("ui_lang", DEFAULT_UI_LANG)
    ui = get_ui(lang)
    user_id = request.session.get("pending_2fa_user_id")
    if not user_id:
        return _login_redirect_with_next(request.session.get("pending_2fa_next", ""))

    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id, is_active=True)
    except User.DoesNotExist:
        next_url = request.session.pop("pending_2fa_next", "") or ""
        request.session.pop("pending_2fa_user_id", None)
        return _login_redirect_with_next(next_url)

    client_ip = request.META.get("REMOTE_ADDR", "")
    resend_cooldown = get_resend_cooldown_remaining(user.pk)
    error = None
    if request.method == "POST":
        if request.POST.get("action") == "resend":
            from accounts_app.services.two_factor import initiate_two_factor

            if is_otp_resend_ip_blocked(client_ip):
                error = ui.get("verify_2fa_resend_rate_limit", "Too many resend attempts.")
            elif resend_cooldown > 0:
                error = ui.get(
                    "verify_2fa_resend_cooldown",
                    "Please wait before requesting a new code.",
                ).format(seconds=resend_cooldown)
            else:
                try:
                    initiate_two_factor(
                        user,
                        lang,
                        base_url=request.build_absolute_uri("/"),
                        is_resend=True,
                    )
                    record_otp_resend_ip(client_ip)
                    resend_cooldown = get_resend_cooldown_remaining(user.pk)
                    messages.success(request, ui.get("verify_2fa_resent", "A new code was sent."))
                except ValueError as exc:
                    if str(exc) == "resend_cooldown":
                        resend_cooldown = get_resend_cooldown_remaining(user.pk)
                        error = ui.get(
                            "verify_2fa_resend_cooldown",
                            "Please wait before requesting a new code.",
                        ).format(seconds=resend_cooldown)
                    else:
                        error = ui.get("login_err_2fa_send", "Could not send verification code.")
        else:
            if is_verify_2fa_ip_blocked(client_ip):
                error = ui.get("verify_2fa_rate_limit", "Too many attempts. Try again later.")
            else:
                code = request.POST.get("otp_code", "")
                if verify_otp(user.pk, code):
                    clear_verify_2fa_failures(client_ip)
                    request.session.pop("pending_2fa_user_id", None)
                    next_url = request.session.pop("pending_2fa_next", "") or ""
                    login(request, user)
                    sync_user_language_after_login(request, user)
                    sync_user_theme_after_login(request, user)
                    return _finish_login(request, user, next_url)
                record_verify_2fa_failure(client_ip)
                error = ui.get("verify_2fa_invalid", "Invalid or expired code.")

    return render(
        request,
        "accounts/verify_2fa.html",
        {
            "error": error,
            "email_hint": _mask_email(user.email),
            "subtitle": ui.get("verify_2fa_subtitle", "").format(email=_mask_email(user.email)),
            "resend_cooldown": resend_cooldown,
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

    Anonymous users: session + cookie.
    Authenticated users: also persist preferred_language on UserProfile.
    """
    explicit = request.GET.get("lang") or request.POST.get("lang")
    if explicit in ("ar", "en"):
        new_lang = explicit
    else:
        current = resolve_ui_lang(request)
        new_lang = "en" if current == "ar" else "ar"

    apply_ui_lang_to_request(request, new_lang)
    if request.user.is_authenticated:
        persist_preferred_language(request.user, new_lang)

    next_url = request.GET.get("next") or request.POST.get("next") or "/"
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"

    response = redirect(next_url)
    set_language_cookie(response, new_lang)
    return response


@require_http_methods(["POST"])
def switch_theme(request):
    """
    Set UI theme to light or dark.

    Anonymous users: session only.
    Authenticated users: also persist preferred_theme on UserProfile.
    """
    from django.http import JsonResponse

    explicit = request.POST.get("theme")
    if explicit in ("light", "dark"):
        new_theme = explicit
    else:
        current = resolve_ui_theme(request)
        new_theme = "light" if current == "dark" else "dark"

    apply_ui_theme_to_request(request, new_theme)
    if request.user.is_authenticated:
        persist_preferred_theme(request.user, new_theme)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"theme": new_theme})

    next_url = request.POST.get("next") or request.GET.get("next") or "/"
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"
    return redirect(next_url)


@login_required
def setup_required_view(request):
    if active_companies_exist():
        return redirect(resolve_default_home(request.user, request))

    lang = request.session.get("ui_lang", DEFAULT_UI_LANG)
    ui = get_ui(lang)
    admin_add_company_url = reverse("admin:audit_app_company_add")

    return render(
        request,
        "accounts/setup_required.html",
        {
            "can_manage_companies": user_can_manage_companies(request.user),
            "admin_add_company_url": admin_add_company_url,
        },
    )


@login_required
def select_company_view(request):
    if not active_companies_exist():
        return redirect("setup_required")

    companies = user_companies(request.user)
    lang = request.session.get("ui_lang", DEFAULT_UI_LANG)
    ui = get_ui(lang)

    if not companies.exists():
        messages.warning(request, ui.get("company_none_assigned", "No company access assigned."))
        return redirect("profile")

    if companies.count() == 1:
        set_active_company(request, companies.first().pk)
        safe_next = _safe_next_url(request.GET.get("next") or request.POST.get("next") or "")
        if safe_next:
            return redirect(safe_next)
        return redirect(resolve_default_home(request.user, request))

    next_url = _safe_next_url(request.GET.get("next") or request.POST.get("next") or "")

    if request.method == "POST":
        raw_id = request.POST.get("company_id", "").strip()
        if raw_id.isdigit() and set_active_company(request, int(raw_id)):
            post_next = _safe_next_url(request.POST.get("next") or "") or resolve_default_home(request.user, request)
            return redirect(post_next)
        messages.error(request, ui.get("company_switch_invalid", "Invalid company selection."))

    return render(
        request,
        "accounts/select_company.html",
        {"companies": companies, "next": next_url},
    )


@login_required
@require_http_methods(["POST"])
def switch_company_view(request):
    lang = request.session.get("ui_lang", DEFAULT_UI_LANG)
    ui = get_ui(lang)
    raw_id = request.POST.get("company_id", "").strip()
    next_url = request.POST.get("next") or resolve_default_home(request.user, request)
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = resolve_default_home(request.user, request)

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

    lang = request.session.get("ui_lang", DEFAULT_UI_LANG)
    ui = get_ui(lang)

    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    force_password = profile.must_change_password_on_login or (
        request.GET.get("force_password") == "1"
        and profile.password_expiry_enabled
        and profile.is_password_expired()
    )

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
                    profile.must_change_password_on_login = False
                    profile.save(
                        update_fields=["password_changed_at", "must_change_password_on_login"]
                    )
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
    from accounts_app.models import UserProfile

    profile, _ = UserProfile.objects.get_or_create(user=user)
    if profile.must_change_password_on_login:
        return redirect(reverse("profile") + "?force_password=1&must_change=1")

    _prepare_company_session_after_login(request, user)
    safe_next = _safe_next_url(next_url)

    if not active_companies_exist():
        return redirect("setup_required")

    if user_must_select_company(user):
        url = reverse("select_company")
        if safe_next:
            url = f"{url}?next={quote(safe_next)}"
        return redirect(url)

    if safe_next:
        return redirect(safe_next)
    return redirect(resolve_default_home(user, request))


def _redirect_after_login(user, request=None):
    if not active_companies_exist():
        return redirect(reverse("setup_required"))

    companies = user_companies(user)
    if companies.count() > 1:
        return redirect(reverse("select_company"))

    return redirect(resolve_default_home(user, request))
