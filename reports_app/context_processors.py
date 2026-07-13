"""Inject UI language strings into every template context."""
from __future__ import annotations

import os
import sys

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from accounts_app.services.user_language import resolve_ui_lang
from accounts_app.services.user_theme import resolve_ui_theme
from audit_app.company_access import (
    active_companies_exist,
    get_active_company,
    user_can_manage_companies,
    user_companies,
    user_must_select_company,
)
from reports_app.dashboard_workflow import (
    has_dashboard_list_perm,
    has_delete_draft_perm,
    has_review_perm,
    has_upload_perm,
)
from django.urls import reverse
from web_strings import get_ui


def ui_context(request) -> dict:
    """
    Injects into every template context:
      lang, is_rtl, dir, ui              — language & translations
      can_upload_files, can_view_dashboards  — permission booleans (safe in templates)
    """
    lang = resolve_ui_lang(request)
    ui_theme = resolve_ui_theme(request)
    can_upload = False
    can_view = False
    can_manage_users = False
    can_delete_dashboards = False
    can_delete_drafts = False
    can_review_dashboards = False
    active_company = None
    user_company_list = []
    needs_company_selection = False
    no_companies_configured = not active_companies_exist()
    can_manage_companies = False

    if hasattr(request, "user") and request.user.is_authenticated:
        u = request.user
        active_company = getattr(request, "active_company", None) or get_active_company(request)
        user_company_list = list(user_companies(u))
        can_upload = has_upload_perm(u, active_company)
        can_view = has_dashboard_list_perm(u, active_company)
        can_delete_dashboards = (
            u.is_superuser
        )
        can_manage_users = u.is_superuser or u.has_perm("auth.change_user")
        can_review_dashboards = has_review_perm(u, active_company)
        can_delete_drafts = has_delete_draft_perm(u, active_company)
        can_manage_companies = user_can_manage_companies(u)
        needs_company_selection = (
            not no_companies_configured
            and user_must_select_company(u)
            and active_company is None
        )

    active_company_logo_url = None
    if active_company and not needs_company_selection and getattr(active_company, "logo", None):
        try:
            if active_company.logo.name:
                active_company_logo_url = reverse("company_logo", args=[active_company.pk])
        except (ValueError, AttributeError):
            active_company_logo_url = None

    return {
        "lang": lang,
        "ui_theme": ui_theme,
        "is_rtl": lang == "ar",
        "dir": "rtl" if lang == "ar" else "ltr",
        "ui": get_ui(lang),
        "can_upload_files": can_upload,
        "can_view_dashboards": can_view,
        "can_delete_dashboards": can_delete_dashboards,
        "can_review_dashboards": can_review_dashboards,
        "can_delete_drafts": can_delete_drafts,
        "can_manage_users": can_manage_users,
        "active_company": active_company,
        "active_company_logo_url": active_company_logo_url,
        "user_companies": user_company_list,
        "show_company_switcher": len(user_company_list) > 1,
        "needs_company_selection": needs_company_selection,
        "no_companies_configured": no_companies_configured,
        "can_manage_companies": can_manage_companies,
    }
