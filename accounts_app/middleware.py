from __future__ import annotations

from django.shortcuts import redirect
from django.urls import reverse

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
        "/api/",
        "/favicon.ico",
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
                    if path != reverse("select_company"):
                        return redirect("select_company")

        return self.get_response(request)

    def _is_exempt(self, path: str) -> bool:
        if path in self.EXEMPT_PATHS:
            return True
        return any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES)


class PasswordExpiryMiddleware:
    """Force password change when older than PASSWORD_MAX_AGE_DAYS."""

    EXEMPT_PREFIXES = ActiveCompanyMiddleware.EXEMPT_PREFIXES
    EXEMPT_PATHS = ActiveCompanyMiddleware.EXEMPT_PATHS + ("/profile/",)

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            path = request.path
            if not self._is_exempt(path) and self._password_expired(user):
                profile_url = reverse("profile") + "?force_password=1"
                return redirect(profile_url)

        return self.get_response(request)

    def _is_exempt(self, path: str) -> bool:
        if path in self.EXEMPT_PATHS:
            return True
        if path.startswith("/profile"):
            return True
        return any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES)

    def _password_expired(self, user) -> bool:
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return profile.is_password_expired()
