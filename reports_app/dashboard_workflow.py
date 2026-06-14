"""Dashboard permissions and draft/approve/reject/soft-delete workflow."""
from __future__ import annotations

import re

from django.db.models import Q, QuerySet
from django.utils import timezone

from audit_app.company_access import active_companies_exist, has_company_perm, user_must_select_company
from audit_app.models import Company, Dashboard, DashboardRejectionLog, DashboardStatus

_DASHBOARD_PK_URL = re.compile(r"^/dashboards/(\d+)(?:/|$)")


def has_review_perm(user, company: Company | None = None) -> bool:
    if not active_companies_exist():
        return False
    if company is None:
        if user.is_superuser and not user_must_select_company(user):
            return True
        return False
    return has_company_perm(user, company, "review")


def has_upload_perm(user, company: Company | None = None) -> bool:
    if not active_companies_exist():
        return False
    if company is None:
        if user.is_superuser and not user_must_select_company(user):
            return True
        return False
    return has_company_perm(user, company, "upload")


def has_view_perm(user, company: Company | None = None) -> bool:
    if not active_companies_exist():
        return False
    if company is None:
        if user.is_superuser and not user_must_select_company(user):
            return True
        return False
    return has_company_perm(user, company, "view")


def has_view_own_only_perm(user, company: Company | None = None) -> bool:
    if company is None:
        return False
    if user.is_superuser:
        return False
    return has_company_perm(user, company, "view_own")


def has_dashboard_list_perm(user, company: Company | None = None) -> bool:
    """May open the dashboard list (any visibility scope within the company)."""
    return (
        has_review_perm(user, company)
        or has_view_perm(user, company)
        or has_view_own_only_perm(user, company)
        or has_upload_perm(user, company)
    )


def has_delete_perm(user) -> bool:
    """Superuser-only access to soft-deleted dashboard trash and restore."""
    return user.is_superuser


def has_delete_draft_perm(user, company: Company | None = None) -> bool:
    if not active_companies_exist():
        return False
    if user.is_superuser:
        return True
    if company is None:
        return False
    return has_company_perm(user, company, "delete_draft")


def can_user_delete_dashboard(
    user,
    dashboard: Dashboard,
    company: Company | None = None,
) -> bool:
    """Superuser-only soft delete for any active dashboard (including published)."""
    if dashboard.is_deleted:
        return False
    if has_delete_perm(user):
        return True
    return False


def user_is_creator(user, dashboard: Dashboard) -> bool:
    return bool(dashboard.created_by_id and dashboard.created_by_id == user.id)


def user_can_see_dashboard(user, dashboard: Dashboard, company: Company | None = None) -> bool:
    if (
        company is not None
        and dashboard.company_id
        and dashboard.company_id != company.id
    ):
        return False
    if dashboard.is_deleted:
        return has_delete_perm(user)
    if dashboard.status == DashboardStatus.PUBLISHED:
        if has_view_perm(user, company or dashboard.company):
            return True
        active = company or dashboard.company
        if user_is_creator(user, dashboard) and (
            has_view_own_only_perm(user, active)
            or has_upload_perm(user, active)
        ):
            return True
        return False
    if has_review_perm(user, company or dashboard.company):
        return True
    return user_is_creator(user, dashboard)


def dashboards_queryset_for_user(user, company: Company | None = None) -> QuerySet[Dashboard]:
    qs = (
        Dashboard.objects.filter(is_deleted=False)
        .select_related("created_by", "upload_session", "reviewed_by", "company")
    )
    if company is not None:
        qs = qs.filter(company=company)
    elif not user.is_superuser:
        return Dashboard.objects.none()

    active = company or None
    if has_review_perm(user, active):
        return qs
    if has_view_perm(user, active):
        return qs.filter(status=DashboardStatus.PUBLISHED)
    if has_view_own_only_perm(user, active):
        return qs.filter(created_by=user)
    if has_upload_perm(user, active):
        filters = Q(status=DashboardStatus.PUBLISHED) | Q(created_by=user)
        return qs.filter(filters)
    return qs.none()


def deleted_dashboards_queryset_for_user(user, company: Company | None = None) -> QuerySet[Dashboard]:
    if not has_delete_perm(user):
        return Dashboard.objects.none()
    qs = (
        Dashboard.objects.filter(is_deleted=True)
        .select_related("created_by", "upload_session", "reviewed_by", "deleted_by", "company")
        .order_by("-deleted_at", "-created_at")
    )
    if company is not None:
        qs = qs.filter(company=company)
    elif not user.is_superuser:
        return Dashboard.objects.none()
    return qs


def get_dashboard_for_review(user, pk: int, company: Company | None = None) -> Dashboard | None:
    """Load a dashboard for approve/reject actions (reviewers only)."""
    if not has_review_perm(user, company):
        return None
    try:
        dashboard = Dashboard.objects.select_related(
            "created_by", "upload_session", "reviewed_by", "company"
        ).get(pk=pk, is_deleted=False)
    except Dashboard.DoesNotExist:
        return None
    if company is not None and dashboard.company_id != company.id:
        return None
    return dashboard


def user_has_company_access(user, company: Company | None) -> bool:
    if company is None:
        return True
    from audit_app.company_access import user_membership

    return user_membership(user, company) is not None


def load_dashboard_cross_company(
    user,
    pk: int,
    *,
    allow_deleted: bool = False,
) -> Dashboard | None:
    """Load a dashboard using its own company context (ignores active company)."""
    try:
        dashboard = Dashboard.objects.select_related(
            "created_by", "upload_session", "reviewed_by", "deleted_by", "company"
        ).get(pk=pk)
    except Dashboard.DoesNotExist:
        return None
    if dashboard.is_deleted:
        if not allow_deleted or not has_delete_perm(user):
            return None
    elif not user_can_see_dashboard(user, dashboard, company=dashboard.company):
        return None
    if dashboard.company_id and not user_has_company_access(user, dashboard.company):
        return None
    return dashboard


def activate_company_for_dashboard(request, dashboard: Dashboard) -> bool:
    """Align session active company with the dashboard tenant before display."""
    from audit_app.company_access import get_active_company, set_active_company

    if not dashboard.company_id:
        return True
    active = get_active_company(request)
    if active and active.pk == dashboard.company_id:
        return True
    if user_has_company_access(request.user, dashboard.company):
        set_active_company(request, dashboard.company_id)
        request.active_company = dashboard.company
        return True
    return False


def dashboard_url_belongs_to_company(path: str, company: Company | None) -> bool:
    """Return False when *path* is a dashboard URL for another company's record."""
    if not company:
        return True
    match = _DASHBOARD_PK_URL.match(path or "")
    if not match:
        return True
    pk = int(match.group(1))
    company_id = (
        Dashboard.objects.filter(pk=pk).values_list("company_id", flat=True).first()
    )
    if company_id is None:
        return True
    return company_id == company.id


def get_dashboard_for_user(
    user,
    pk: int,
    *,
    company: Company | None = None,
    allow_deleted: bool = False,
) -> Dashboard | None:
    try:
        dashboard = Dashboard.objects.select_related(
            "created_by", "upload_session", "reviewed_by", "deleted_by", "company"
        ).get(pk=pk)
    except Dashboard.DoesNotExist:
        return None
    if dashboard.is_deleted:
        if not allow_deleted or not has_delete_perm(user):
            return None
        if (
            company is not None
            and dashboard.company_id
            and dashboard.company_id != company.id
        ):
            return None
        return dashboard
    if not user_can_see_dashboard(user, dashboard, company=company or dashboard.company):
        return None
    if (
        company is not None
        and dashboard.company_id
        and dashboard.company_id != company.id
    ):
        return None
    return dashboard


def approve_dashboard(dashboard: Dashboard, reviewer) -> None:
    dashboard.status = DashboardStatus.PUBLISHED
    dashboard.published_at = timezone.now()
    dashboard.reviewed_by = reviewer
    dashboard.save(update_fields=["status", "published_at", "reviewed_by"])


def reject_dashboard(dashboard: Dashboard, reviewer, reason: str) -> DashboardRejectionLog:
    log = DashboardRejectionLog.objects.create(
        dashboard=dashboard,
        reason=reason.strip(),
        rejected_by=reviewer,
    )
    dashboard.status = DashboardStatus.REJECTED
    dashboard.published_at = None
    dashboard.reviewed_by = reviewer
    dashboard.save(update_fields=["status", "published_at", "reviewed_by"])
    return log


def mark_dashboard_draft(dashboard: Dashboard) -> None:
    dashboard.status = DashboardStatus.DRAFT
    dashboard.published_at = None
    dashboard.save(update_fields=["status", "published_at"])


def can_user_resubmit(user, dashboard: Dashboard, company: Company | None = None) -> bool:
    active = company or dashboard.company
    return (
        not dashboard.is_deleted
        and dashboard.status in (DashboardStatus.REJECTED, DashboardStatus.DRAFT)
        and user_is_creator(user, dashboard)
        and has_upload_perm(user, active)
        and (active is None or dashboard.company_id == active.id or user.is_superuser)
    )


def can_user_review(user, dashboard: Dashboard, company: Company | None = None) -> bool:
    active = company or dashboard.company
    return (
        has_review_perm(user, active)
        and not dashboard.is_deleted
        and dashboard.status == DashboardStatus.DRAFT
        and (active is None or dashboard.company_id == active.id or user.is_superuser)
    )


def soft_delete_dashboard(dashboard: Dashboard, user) -> None:
    dashboard.is_deleted = True
    dashboard.deleted_at = timezone.now()
    dashboard.deleted_by = user
    dashboard.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])


def restore_dashboard(dashboard: Dashboard) -> None:
    dashboard.is_deleted = False
    dashboard.deleted_at = None
    dashboard.deleted_by = None
    dashboard.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])
