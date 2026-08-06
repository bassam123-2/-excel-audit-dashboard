"""Password expiry redirect and active-company session enforcement."""
from __future__ import annotations

from urllib.parse import quote

from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from accounts_app.models import UserProfile
from audit_app.company_access import active_companies_exist, get_active_company, user_must_select_company


class ActiveCompanyMiddleware:
    """Attach active company to the request and enforce company selection."""

    EXEMPT_PREFIXES = (
        "/static/",
        "/media/",
        "/admin/",
    )
    EXEMPT_PATHS = (
        "/login/",
        "/logout/",
        "/verify-2fa/",
        "/select-company/",
        "/switch-company/",
        "/setup-required/",
        "/profile/",
        "/lang/switch/",
        "/theme/switch/",
        "/api/",
        "/favicon.ico",
        "/robots.txt",
        "/manifest.webmanifest",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.active_company = None
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            request.active_company = get_active_company(request)

            path = request.path
            if not self._is_exempt(path):
                if not active_companies_exist():
                    setup_path = reverse("setup_required")
                    if path != setup_path:
                        return redirect(setup_path)
                elif user_must_select_company(user) and request.active_company is None:
                    select_path = reverse("select_company")
                    if path != select_path and not path.startswith(f"{select_path}?"):
                        next_path = quote(request.get_full_path())
                        return redirect(f"{select_path}?next={next_path}")

        return self.get_response(request)

    def _is_exempt(self, path: str) -> bool:
        if path.startswith("/set-password/"):
            return True
        if path in self.EXEMPT_PATHS:
            return True
        return any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES)


class PasswordExpiryMiddleware:
    """Force password change when older than PASSWORD_MAX_AGE_DAYS or admin flag set."""

    EXEMPT_PREFIXES = ActiveCompanyMiddleware.EXEMPT_PREFIXES
    EXEMPT_PATHS = ActiveCompanyMiddleware.EXEMPT_PATHS + ("/profile/",)

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            path = request.path
            if not self._is_exempt(path) and self._must_change_password(user):
                profile_url = reverse("profile") + "?force_password=1&must_change=1"
                return redirect(profile_url)
            if not self._is_exempt(path) and self._password_expired(user):
                profile_url = reverse("profile") + "?force_password=1"
                return redirect(profile_url)

        return self.get_response(request)

    def _is_exempt(self, path: str) -> bool:
        if path.startswith("/set-password/"):
            return True
        if path in self.EXEMPT_PATHS:
            return True
        if path.startswith("/profile"):
            return True
        return any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES)


    def _must_change_password(self, user) -> bool:
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return bool(profile.must_change_password_on_login)

    def _password_expired(self, user) -> bool:
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return profile.is_password_expired()


class IdleSessionMiddleware:
    """Log out authenticated users after a period of inactivity."""

    SESSION_LAST_ACTIVITY_KEY = "_last_activity"
    EXEMPT_PREFIXES = (
        "/static/",
        "/media/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings

        user = getattr(request, "user", None)
        if user and user.is_authenticated and not self._is_exempt(request.path):
            timeout = int(getattr(settings, "IDLE_SESSION_TIMEOUT_SECONDS", 3600))
            now_ts = timezone.now().timestamp()
            last_ts = request.session.get(self.SESSION_LAST_ACTIVITY_KEY)
            if last_ts is not None and (now_ts - float(last_ts)) > timeout:
                logout(request)
                request.session.flush()
                return redirect(reverse("login") + "?session_expired=1")
            request.session[self.SESSION_LAST_ACTIVITY_KEY] = now_ts
            request.session.modified = True

        return self.get_response(request)

    def _is_exempt(self, path: str) -> bool:
        if path.startswith("/set-password/"):
            return True
        if path in ActiveCompanyMiddleware.EXEMPT_PATHS:
            return True
        if path.startswith("/profile"):
            return True
        return any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES)


class ProjectTimezoneMiddleware:
    """Activate the configured project timezone for each request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from accounts_app.services.project_timezone import activate_project_timezone

        activate_project_timezone()
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()
