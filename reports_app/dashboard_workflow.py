"""Dashboard permissions and draft/submit/approve/reject/workflow/soft-delete."""
from __future__ import annotations

import re
from typing import Any

from django.db.models import Q, QuerySet
from django.utils import timezone

from audit_app.company_access import (
    active_companies_exist,
    company_is_effectively_active,
    has_company_perm,
    resolve_tenant_company,
    user_must_select_company,
)
from audit_app.models import COMPANY_KIND_MAIN, Company, Dashboard, DashboardRejectionLog, DashboardStatus
from reports_app.workflow_engine import (
    cancel_workflow_on_reject,
    company_uses_workflow_v2,
    get_workflow_instance,
    publish_dashboard,
    start_workflow_after_approval,
    submit_dashboard_for_review,
    workflow_progress_label,
)

_DASHBOARD_PK_URL = re.compile(r"^/dashboards/(\d+)(?:/|$)")

FILTER_ALL = "all"
FILTER_PENDING_REVIEW = "pending_review"
FILTER_PENDING_ACK = "pending_ack"
FILTER_PUBLISHED = "published"
FILTER_MINE = "mine"
FILTER_REJECTED = "rejected"

_REVIEWABLE_STATUSES = (
    DashboardStatus.UNDER_REVIEW,
    DashboardStatus.IN_WORKFLOW,
)
_PRIVATE_CREATOR_STATUSES = (
    DashboardStatus.DRAFT,
    DashboardStatus.REJECTED,
)


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
    return (
        has_review_perm(user, company)
        or has_view_perm(user, company)
        or has_view_own_only_perm(user, company)
        or has_upload_perm(user, company)
    )


def has_delete_perm(user) -> bool:
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
    if dashboard.is_deleted:
        return False
    if has_delete_perm(user):
        return True
    active = company or dashboard.company
    if (
        dashboard.status == DashboardStatus.DRAFT
        and has_delete_draft_perm(user, active)
        and user_is_creator(user, dashboard)
    ):
        return active is None or dashboard.company_id == active.id or user.is_superuser
    return False


def user_is_creator(user, dashboard: Dashboard) -> bool:
    return bool(dashboard.created_by_id and dashboard.created_by_id == user.id)


def _uses_v2(company: Company | None) -> bool:
    return company_uses_workflow_v2(company)


def _base_dashboards_qs(company: Company | None) -> QuerySet[Dashboard]:
    qs = (
        Dashboard.objects.filter(is_deleted=False, company__is_active=True)
        .filter(company__company_kind=COMPANY_KIND_MAIN)
        .select_related(
            "created_by",
            "upload_session",
            "reviewed_by",
            "company",
            "workflow_instance",
            "workflow_instance__current_assignee",
        )
    )
    if company is not None:
        qs = qs.filter(company=company)
    return qs


def _visibility_q(user, company: Company | None) -> Q:
    """Build OR conditions for dashboards visible to *user* within *company*."""
    if user.is_superuser and company is None:
        return Q()

    q = Q(created_by=user)

    if has_review_perm(user, company):
        q |= Q(status__in=[*_REVIEWABLE_STATUSES, DashboardStatus.PUBLISHED])

    if has_view_perm(user, company):
        q |= Q(status=DashboardStatus.PUBLISHED)

    if has_upload_perm(user, company) and not has_view_perm(user, company):
        q |= Q(status=DashboardStatus.PUBLISHED)

    q |= Q(
        status=DashboardStatus.IN_WORKFLOW,
        workflow_instance__current_assignee=user,
    )

    return q


def user_can_see_dashboard(user, dashboard: Dashboard, company: Company | None = None) -> bool:
    if (
        company is not None
        and dashboard.company_id
        and dashboard.company_id != company.id
    ):
        return False
    if dashboard.is_deleted:
        return has_delete_perm(user)

    active = company or dashboard.company

    if user.is_superuser:
        return True

    if dashboard.status in _PRIVATE_CREATOR_STATUSES:
        return user_is_creator(user, dashboard)

    if user_is_creator(user, dashboard):
        return True

    if dashboard.status == DashboardStatus.PUBLISHED:
        if has_view_perm(user, active):
            return True
        if has_upload_perm(user, active):
            return True
        return has_view_own_only_perm(user, active)

    if dashboard.status in _REVIEWABLE_STATUSES:
        if has_review_perm(user, active):
            return True
        instance = get_workflow_instance(dashboard)
        if (
            dashboard.status == DashboardStatus.IN_WORKFLOW
            and instance
            and instance.current_assignee_id == user.id
        ):
            return True

    return False


def dashboards_queryset_for_user(user, company: Company | None = None) -> QuerySet[Dashboard]:
    if company is None and not user.is_superuser:
        return Dashboard.objects.none()

    qs = _base_dashboards_qs(company)
    if user.is_superuser and company is None:
        return qs

    return qs.filter(_visibility_q(user, company)).distinct()


def filter_dashboards_queryset(
    qs: QuerySet[Dashboard],
    user,
    company: Company | None,
    filter_key: str,
) -> QuerySet[Dashboard]:
    key = (filter_key or FILTER_ALL).strip() or FILTER_ALL
    if key == FILTER_ALL:
        return qs
    if key == FILTER_PENDING_REVIEW:
        return qs.filter(status=DashboardStatus.UNDER_REVIEW)
    if key == FILTER_PENDING_ACK:
        return qs.filter(
            status=DashboardStatus.IN_WORKFLOW,
            workflow_instance__current_assignee=user,
        )
    if key == FILTER_PUBLISHED:
        return qs.filter(status=DashboardStatus.PUBLISHED)
    if key == FILTER_MINE:
        return qs.filter(created_by=user)
    if key == FILTER_REJECTED:
        return qs.filter(status=DashboardStatus.REJECTED, created_by=user)
    return qs


def available_dashboard_filters(
    user,
    company: Company | None,
    base_qs: QuerySet[Dashboard] | None = None,
) -> list[dict[str, Any]]:
    qs = base_qs if base_qs is not None else dashboards_queryset_for_user(user, company)
    filters: list[dict[str, Any]] = []

    def add(key: str, label_key: str, count_qs: QuerySet[Dashboard]) -> None:
        count = count_qs.count()
        if count > 0 or key == FILTER_ALL:
            filters.append({"key": key, "label_key": label_key, "count": count})

    add(FILTER_ALL, "dl_filter_all", qs)

    if has_review_perm(user, company):
        pending = qs.filter(status=DashboardStatus.UNDER_REVIEW)
        if pending.exists() or len(filters) > 1:
            filters.append(
                {
                    "key": FILTER_PENDING_REVIEW,
                    "label_key": "dl_filter_pending_review",
                    "count": pending.count(),
                }
            )

    pending_ack = qs.filter(
        status=DashboardStatus.IN_WORKFLOW,
        workflow_instance__current_assignee=user,
    )
    if pending_ack.exists():
        filters.append(
            {
                "key": FILTER_PENDING_ACK,
                "label_key": "dl_filter_pending_ack",
                "count": pending_ack.count(),
            }
        )

    if has_view_perm(user, company):
        published = qs.filter(status=DashboardStatus.PUBLISHED)
        if published.exists() or (has_review_perm(user, company) and len(filters) > 1):
            filters.append(
                {
                    "key": FILTER_PUBLISHED,
                    "label_key": "dl_filter_published",
                    "count": published.count(),
                }
            )

    mine = qs.filter(created_by=user)
    if mine.exists() and (has_upload_perm(user, company) or has_review_perm(user, company)):
        if not (len(filters) == 2 and filters[0]["key"] == FILTER_ALL):
            filters.append(
                {
                    "key": FILTER_MINE,
                    "label_key": "dl_filter_mine",
                    "count": mine.count(),
                }
            )

    rejected = qs.filter(status=DashboardStatus.REJECTED, created_by=user)
    if rejected.exists():
        filters.append(
            {
                "key": FILTER_REJECTED,
                "label_key": "dl_filter_rejected",
                "count": rejected.count(),
            }
        )

    if len(filters) <= 1:
        return []
    return filters


def deleted_dashboards_queryset_for_user(user, company: Company | None = None) -> QuerySet[Dashboard]:
    if not has_delete_perm(user):
        return Dashboard.objects.none()
    qs = (
        Dashboard.objects.filter(is_deleted=True, company__is_active=True)
        .select_related("created_by", "upload_session", "reviewed_by", "deleted_by", "company")
        .order_by("-deleted_at", "-created_at")
    )
    if company is not None:
        qs = qs.filter(company=company)
    elif not user.is_superuser:
        return Dashboard.objects.none()
    return qs


def get_dashboard_for_review(user, pk: int, company: Company | None = None) -> Dashboard | None:
    if not has_review_perm(user, company):
        return None
    try:
        dashboard = Dashboard.objects.select_related(
            "created_by",
            "upload_session",
            "reviewed_by",
            "company",
            "workflow_instance",
        ).get(pk=pk, is_deleted=False)
    except Dashboard.DoesNotExist:
        return None
    if company is not None and dashboard.company_id != company.id:
        return None
    if not user_can_see_dashboard(user, dashboard, company=company or dashboard.company):
        return None
    return dashboard


def user_has_company_access(user, company: Company | None) -> bool:
    if company is None:
        return True
    if not company_is_effectively_active(company):
        return False
    from audit_app.company_access import user_membership

    return user_membership(user, company) is not None


def load_dashboard_cross_company(
    user,
    pk: int,
    *,
    allow_deleted: bool = False,
) -> Dashboard | None:
    try:
        dashboard = Dashboard.objects.select_related(
            "created_by",
            "upload_session",
            "reviewed_by",
            "deleted_by",
            "company",
            "workflow_instance",
            "workflow_instance__current_assignee",
        ).get(pk=pk)
    except Dashboard.DoesNotExist:
        return None
    if dashboard.is_deleted:
        if not allow_deleted or not has_delete_perm(user):
            return None
    elif not user_can_see_dashboard(user, dashboard, company=dashboard.company):
        return None
    tenant = resolve_tenant_company(dashboard.company) if dashboard.company_id else None
    if dashboard.company_id and (
        tenant is None
        or not dashboard.company.is_main
        or not company_is_effectively_active(tenant)
    ):
        return None
    if dashboard.company_id and not user_has_company_access(user, tenant):
        return None
    return dashboard


def activate_company_for_dashboard(request, dashboard: Dashboard) -> bool:
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
            "created_by",
            "upload_session",
            "reviewed_by",
            "deleted_by",
            "company",
            "workflow_instance",
            "workflow_instance__current_assignee",
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


def can_user_submit(user, dashboard: Dashboard, company: Company | None = None) -> bool:
    active = company or dashboard.company
    return (
        not dashboard.is_deleted
        and dashboard.status == DashboardStatus.DRAFT
        and user_is_creator(user, dashboard)
        and has_upload_perm(user, active)
        and _uses_v2(active)
        and (active is None or dashboard.company_id == active.id or user.is_superuser)
    )


def submit_dashboard(user, dashboard: Dashboard, company: Company | None = None) -> None:
    if not can_user_submit(user, dashboard, company):
        raise PermissionError("submit_forbidden")
    submit_dashboard_for_review(dashboard)


def approve_dashboard(dashboard: Dashboard, reviewer) -> str:
    """
    Approve dashboard: start workflow or publish directly.

    Returns: 'workflow' | 'published'
    """
    company = dashboard.company
    if company and _uses_v2(company) and start_workflow_after_approval(dashboard, reviewer):
        return "workflow"
    publish_dashboard(dashboard, reviewer)
    return "published"


def reject_dashboard(dashboard: Dashboard, reviewer, reason: str) -> DashboardRejectionLog:
    cancel_workflow_on_reject(dashboard)
    log = DashboardRejectionLog.objects.create(
        dashboard=dashboard,
        reason=reason.strip(),
        rejected_by=reviewer,
    )
    dashboard.status = DashboardStatus.REJECTED
    dashboard.published_at = None
    dashboard.submitted_at = None
    dashboard.reviewed_by = reviewer
    dashboard.save(
        update_fields=["status", "published_at", "submitted_at", "reviewed_by"]
    )
    return log


def mark_dashboard_draft(dashboard: Dashboard) -> None:
    cancel_workflow_on_reject(dashboard)
    dashboard.status = DashboardStatus.DRAFT
    dashboard.published_at = None
    dashboard.submitted_at = None
    dashboard.save(update_fields=["status", "published_at", "submitted_at"])


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
    if not has_review_perm(user, active) or dashboard.is_deleted:
        return False
    if active is not None and dashboard.company_id != active.id and not user.is_superuser:
        return False

    company_v2 = _uses_v2(active)
    if company_v2:
        return dashboard.status in _REVIEWABLE_STATUSES
    return dashboard.status == DashboardStatus.DRAFT


def can_user_acknowledge(user, dashboard: Dashboard, company: Company | None = None) -> bool:
    if dashboard.is_deleted or dashboard.status != DashboardStatus.IN_WORKFLOW:
        return False
    instance = get_workflow_instance(dashboard)
    if instance is None or instance.current_assignee_id != user.id:
        return False
    active = company or dashboard.company
    if active is not None and dashboard.company_id != active.id and not user.is_superuser:
        return False
    return True


def can_user_reject(user, dashboard: Dashboard, company: Company | None = None) -> bool:
    return can_user_review(user, dashboard, company)


def dashboard_workflow_progress(dashboard: Dashboard) -> str | None:
    return workflow_progress_label(dashboard)


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
