"""URL routes for login, 2FA, profile, and company selection."""

from django.urls import path

from .views import (
    login_view,
    logout_view,
    profile_view,
    select_company_view,
    setup_required_view,
    switch_company_view,
    switch_language,
    verify_2fa_view,
)

urlpatterns = [
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("verify-2fa/", verify_2fa_view, name="verify_2fa"),
    path("profile/", profile_view, name="profile"),
    path("setup-required/", setup_required_view, name="setup_required"),
    path("select-company/", select_company_view, name="select_company"),
    path("switch-company/", switch_company_view, name="switch_company"),
    path("lang/switch/", switch_language, name="switch_language"),
]
