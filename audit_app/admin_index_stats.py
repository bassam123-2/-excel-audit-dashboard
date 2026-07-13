"""Admin dashboard index summary stats with changelist filter links."""

from __future__ import annotations

from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from audit_app.models import COMPANY_KIND_MAIN, COMPANY_KIND_SUBSIDIARY, Company


def _changelist_url(view_name: str, params: dict[str, str]) -> str:
    base = reverse(view_name)
    if not params:
        return base
    return f"{base}?{urlencode(params)}"


def _user_can_view_companies(user) -> bool:
    return bool(
        user
        and user.is_active
        and (
            user.is_superuser
            or user.has_perm("audit_app.view_company")
        )
    )


def _user_can_view_users(user) -> bool:
    return bool(
        user
        and user.is_active
        and (
            user.is_superuser
            or user.has_perm("auth.view_user")
        )
    )


def build_admin_index_stat_groups(user=None) -> list[dict]:
    """Return grouped index stats the user is allowed to see."""
    groups: list[dict] = []
    show_companies = _user_can_view_companies(user)
    show_users = _user_can_view_users(user)

    if show_companies:
        company_qs = Company.objects.filter(is_deleted=False)
        company_params = {"deleted": "active"}
        groups.append(
            {
                "key": "companies",
                "title": _("Companies"),
                "icon": "bi-building-fill",
                "tone": "companies",
                "items": [
                    {
                        "label": _("Total companies"),
                        "value": company_qs.count(),
                        "url": _changelist_url(
                            "admin:audit_app_company_changelist",
                            company_params,
                        ),
                    },
                    {
                        "label": _("Active main companies"),
                        "value": company_qs.filter(
                            company_kind=COMPANY_KIND_MAIN,
                            is_active=True,
                        ).count(),
                        "url": _changelist_url(
                            "admin:audit_app_company_changelist",
                            {
                                **company_params,
                                "company_kind": COMPANY_KIND_MAIN,
                                "is_active": "1",
                            },
                        ),
                    },
                    {
                        "label": _("Active subsidiaries"),
                        "value": company_qs.filter(
                            company_kind=COMPANY_KIND_SUBSIDIARY,
                            is_active=True,
                        ).count(),
                        "url": _changelist_url(
                            "admin:audit_app_company_changelist",
                            {
                                **company_params,
                                "company_kind": COMPANY_KIND_SUBSIDIARY,
                                "is_active": "1",
                            },
                        ),
                    },
                ],
            }
        )

    if show_users:
        User = get_user_model()
        user_qs = User.objects.exclude(profile__is_deleted=True)
        user_params = {"deleted": "active"}
        groups.append(
            {
                "key": "users",
                "title": _("Users"),
                "icon": "bi-people-fill",
                "tone": "users",
                "items": [
                    {
                        "label": _("Total users"),
                        "value": user_qs.count(),
                        "url": _changelist_url(
                            "admin:auth_user_changelist",
                            user_params,
                        ),
                    },
                    {
                        "label": _("Active users"),
                        "value": user_qs.filter(is_active=True).count(),
                        "url": _changelist_url(
                            "admin:auth_user_changelist",
                            {**user_params, "is_active": "1"},
                        ),
                    },
                    {
                        "label": _("Inactive users"),
                        "value": user_qs.filter(is_active=False).count(),
                        "url": _changelist_url(
                            "admin:auth_user_changelist",
                            {**user_params, "is_active": "0"},
                        ),
                    },
                    {
                        "label": _("Users without 2FA"),
                        "value": user_qs.filter(
                            Q(profile__two_factor_enabled=False)
                            | Q(profile__isnull=True)
                        ).count(),
                        "url": _changelist_url(
                            "admin:auth_user_changelist",
                            {**user_params, "two_factor": "no"},
                        ),
                    },
                ],
            }
        )

    return groups
