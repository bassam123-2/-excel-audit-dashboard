"""Post-auth default destination resolution."""
from __future__ import annotations

from django.urls import reverse

from audit_app.company_access import (
    get_active_company,
    has_company_perm,
    list_nav_template_types,
    user_companies,
    user_must_select_company,
)
from reports_app.dashboard_workflow import has_dashboard_list_perm


def nav_template_sections(user, company, ui: dict | None = None) -> list[dict]:
    """Sidebar sections: one block per dashboard template type the user can use."""
    sections: list[dict] = []
    if not user or not getattr(user, "is_authenticated", False) or company is None:
        return sections
    for template in list_nav_template_types():
        code = template.code
        can_upload = has_company_perm(user, company, "upload", code)
        can_view = has_dashboard_list_perm(user, company, code)
        if not can_upload and not can_view:
            continue
        label = ui.get(f"template_nav_{code}") if ui else None
        sections.append(
            {
                "code": code,
                "name": label or template.name,
                "icon": getattr(template, "icon", None) or "bi-grid",
                "can_upload": can_upload,
                "can_view": can_view,
                "upload_url": f"{reverse('upload')}?template={code}",
                "list_url": f"{reverse('dashboard_list')}?template={code}",
            }
        )
    return sections


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

    sections = nav_template_sections(user, active)
    for section in sections:
        if section["can_view"]:
            return section["list_url"]
    for section in sections:
        if section["can_upload"]:
            return section["upload_url"]
    if has_dashboard_list_perm(user, active):
        return reverse("dashboard_list")
    return reverse("profile")
