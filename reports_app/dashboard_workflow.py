from __future__ import annotations

from django.db.models import Q, QuerySet
from django.utils import timezone

from audit_app.models import Dashboard, DashboardRejectionLog, DashboardStatus


def has_review_perm(user) -> bool:
    return (
        user.is_staff
        or user.is_superuser
        or user.has_perm("audit_app.can_review_dashboards")
    )


def has_upload_perm(user) -> bool:
    return user.is_staff or user.is_superuser or user.has_perm("audit_app.can_upload_files")


def has_view_perm(user) -> bool:
    return (
        user.is_staff
        or user.is_superuser
        or user.has_perm("audit_app.can_view_dashboards")
        or user.has_perm("audit_app.can_upload_files")
    )


def has_delete_perm(user) -> bool:
    """Only admins explicitly granted remove/restore permission (plus superuser)."""
    return user.is_superuser or user.has_perm("audit_app.can_delete_dashboards")


def user_is_creator(user, dashboard: Dashboard) -> bool:
    return bool(dashboard.created_by_id and dashboard.created_by_id == user.id)


def user_can_see_dashboard(user, dashboard: Dashboard) -> bool:
    if dashboard.is_deleted:
        return has_delete_perm(user)
    if dashboard.status == DashboardStatus.PUBLISHED:
        return has_view_perm(user)
    if has_review_perm(user):
        return True
    return user_is_creator(user, dashboard)


def dashboards_queryset_for_user(user) -> QuerySet[Dashboard]:
    qs = (
        Dashboard.objects.filter(is_deleted=False)
        .select_related("created_by", "upload_session", "reviewed_by")
    )
    if has_review_perm(user):
        return qs
    filters = Q(status=DashboardStatus.PUBLISHED)
    if has_upload_perm(user):
        filters |= Q(created_by=user)
    elif has_view_perm(user):
        return qs.filter(status=DashboardStatus.PUBLISHED)
    else:
        return qs.none()
    return qs.filter(filters)


def deleted_dashboards_queryset_for_user(user) -> QuerySet[Dashboard]:
    if not has_delete_perm(user):
        return Dashboard.objects.none()
    return (
        Dashboard.objects.filter(is_deleted=True)
        .select_related("created_by", "upload_session", "reviewed_by", "deleted_by")
        .order_by("-deleted_at", "-created_at")
    )


def get_dashboard_for_review(user, pk: int) -> Dashboard | None:
    """Load a dashboard for approve/reject actions (reviewers only)."""
    if not has_review_perm(user):
        return None
    try:
        return Dashboard.objects.select_related(
            "created_by", "upload_session", "reviewed_by"
        ).get(pk=pk, is_deleted=False)
    except Dashboard.DoesNotExist:
        return None


def get_dashboard_for_user(user, pk: int, *, allow_deleted: bool = False) -> Dashboard | None:
    try:
        dashboard = Dashboard.objects.select_related(
            "created_by", "upload_session", "reviewed_by", "deleted_by"
        ).get(pk=pk)
    except Dashboard.DoesNotExist:
        return None
    if dashboard.is_deleted:
        if not allow_deleted or not has_delete_perm(user):
            return None
        return dashboard
    if not user_can_see_dashboard(user, dashboard):
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


def can_user_resubmit(user, dashboard: Dashboard) -> bool:
    return (
        not dashboard.is_deleted
        and dashboard.status == DashboardStatus.REJECTED
        and user_is_creator(user, dashboard)
        and has_upload_perm(user)
    )


def can_user_review(user, dashboard: Dashboard) -> bool:
    return (
        has_review_perm(user)
        and not dashboard.is_deleted
        and dashboard.status == DashboardStatus.DRAFT
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
