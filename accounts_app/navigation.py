"""Post-auth default destination resolution."""
from __future__ import annotations

from django.urls import reverse

from audit_app.company_access import get_active_company, user_companies, user_must_select_company
from reports_app.dashboard_workflow import has_dashboard_list_perm


def resolve_default_home(user, request=None) -> str:
    """Return the URL path for the user's default home screen."""
    active = None
    if request is not None:
        active = get_active_company(request)
        if user_must_select_company(user) and not active:
            return reverse("select_company")
    elif user_must_select_company(user):
        return reverse("select_company")

    if active is None:
        companies = user_companies(user)
        if companies.count() == 1:
            active = companies.first()

    if has_dashboard_list_perm(user, active):
        return reverse("dashboard_list")
    return reverse("profile")
