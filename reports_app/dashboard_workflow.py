"""Dashboard permissions and draft/submit/publish/return/soft-delete."""
from __future__ import annotations

import re
from typing import Any

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from audit_app.company_access import (
    active_companies_exist,
    company_is_effectively_active,
    get_enabled_attachment_kinds,
    has_company_perm,
    resolve_tenant_company,
    template_codes_with_perm,
    user_must_select_company,
)
from audit_app.models import (
    ATTACHMENT_KIND_CODES,
    COMPANY_KIND_MAIN,
    Company,
    CompanyMembership,
    CompanyMembershipTemplateAccess,
    Dashboard,
    DashboardRejectionLog,
    DashboardStatus,
    DashboardViewer,
)
from reports_app.workflow_engine import (
    company_uses_workflow_v2,
    publish_dashboard,
    submit_dashboard_for_review,
)

_DASHBOARD_PK_URL = re.compile(r"^/dashboards/(\d+)(?:/|$)")

FILTER_ALL = "all"
FILTER_PENDING_REVIEW = "pending_review"
FILTER_PUBLISHED = "published"
FILTER_MINE = "mine"
FILTER_REJECTED = "rejected"
FILTER_DRAFT = "draft"

_REVIEWABLE_STATUSES = (DashboardStatus.UNDER_REVIEW,)
_PRIVATE_CREATOR_STATUSES = (
    DashboardStatus.DRAFT,
    DashboardStatus.REJECTED,
)


def has_review_perm(
    user, company: Company | None = None, template_code: str | None = None
) -> bool:
    if not active_companies_exist():
        return False
    if company is None:
        if user.is_superuser and not user_must_select_company(user):
            return True
        return False
    return has_company_perm(user, company, "review", template_code)


def has_upload_perm(
    user, company: Company | None = None, template_code: str | None = None
) -> bool:
    if not active_companies_exist():
        return False
    if company is None:
        if user.is_superuser and not user_must_select_company(user):
            return True
        return False
    return has_company_perm(user, company, "upload", template_code)


def has_assign_viewers_perm(
    user, company: Company | None = None, template_code: str | None = None
) -> bool:
    if not active_companies_exist():
        return False
    if company is None:
        if user.is_superuser and not user_must_select_company(user):
            return True
        return False
    return has_company_perm(user, company, "assign_viewers", template_code)


def has_view_own_only_perm(
    user, company: Company | None = None, template_code: str | None = None
) -> bool:
    if company is None:
        return False
    if user.is_superuser:
        return False
    return has_company_perm(user, company, "view_own", template_code)


def user_has_dashboard_viewer_grant(
    user, company: Company | None = None, template_code: str | None = None
) -> bool:
    if company is None:
        return False
    qs = DashboardViewer.objects.filter(
        user=user,
        dashboard__company=company,
        dashboard__is_deleted=False,
    )
    if template_code:
        qs = qs.filter(dashboard__template_type=template_code)
    return qs.exists()


def has_dashboard_list_perm(
    user, company: Company | None = None, template_code: str | None = None
) -> bool:
    return (
        has_review_perm(user, company, template_code)
        or has_assign_viewers_perm(user, company, template_code)
        or has_view_own_only_perm(user, company, template_code)
        or has_upload_perm(user, company, template_code)
        or user_has_dashboard_viewer_grant(user, company, template_code)
    )


def has_delete_perm(user) -> bool:
    return user.is_superuser


def has_delete_draft_perm(
    user, company: Company | None = None, template_code: str | None = None
) -> bool:
    if not active_companies_exist():
        return False
    if user.is_superuser:
        return True
    if company is None:
        return False
    return has_company_perm(user, company, "delete_draft", template_code)


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
        and has_delete_draft_perm(user, active, dashboard.template_type)
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
        Dashboard.objects.filter(
            is_deleted=False,
            company__is_active=True,
            company__is_deleted=False,
        )
        .filter(company__company_kind=COMPANY_KIND_MAIN)
        .select_related(
            "created_by",
            "upload_session",
            "reviewed_by",
            "company",
        )
    )
    if company is not None:
        qs = qs.filter(company=company)
    return qs


def _published_viewer_q(user) -> Q:
    return Q(
        status=DashboardStatus.PUBLISHED,
        viewers__user=user,
    )


def _visibility_q(user, company: Company | None) -> Q:
    """Build OR conditions for dashboards visible to *user* within *company*."""
    if user.is_superuser and company is None:
        return Q()

    q = Q(created_by=user)

    review_codes = template_codes_with_perm(user, company, "review")
    if review_codes:
        q |= Q(
            template_type__in=review_codes,
            status__in=[*_REVIEWABLE_STATUSES, DashboardStatus.PUBLISHED],
        )

    assign_codes = template_codes_with_perm(user, company, "assign_viewers")
    if assign_codes:
        q |= Q(template_type__in=assign_codes, status=DashboardStatus.PUBLISHED)

    q |= _published_viewer_q(user)

    return q


def user_can_see_dashboard(user, dashboard: Dashboard, company: Company | None = None) -> bool:
    if (
        company is not None
        and dashboard.company_id
        and dashboard.company_id != company.id
    ):
        return False
    if dashboard.is_deleted:
        return False

    active = company or dashboard.company

    if user.is_superuser:
        return True

    if dashboard.status in _PRIVATE_CREATOR_STATUSES:
        return user_is_creator(user, dashboard)

    if user_is_creator(user, dashboard):
        return True

    if dashboard.status == DashboardStatus.PUBLISHED:
        if has_review_perm(user, active, dashboard.template_type):
            return True
        if has_assign_viewers_perm(user, active, dashboard.template_type):
            return True
        return DashboardViewer.objects.filter(
            dashboard=dashboard,
            user=user,
        ).exists()

    if dashboard.status in _REVIEWABLE_STATUSES:
        return has_review_perm(user, active, dashboard.template_type)

    return False


def dashboards_queryset_for_user(user, company: Company | None = None) -> QuerySet[Dashboard]:
    if company is None and not user.is_superuser:
        return Dashboard.objects.none()

    qs = _base_dashboards_qs(company)
    if user.is_superuser:
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
    if key == FILTER_PUBLISHED:
        return qs.filter(status=DashboardStatus.PUBLISHED)
    if key == FILTER_MINE:
        return qs.filter(created_by=user)
    if key == FILTER_REJECTED:
        return qs.filter(status=DashboardStatus.REJECTED, created_by=user)
    if key == FILTER_DRAFT:
        return qs.filter(status=DashboardStatus.DRAFT)
    return qs


def available_dashboard_filters(
    user,
    company: Company | None,
    base_qs: QuerySet[Dashboard] | None = None,
    template_code: str | None = None,
) -> list[dict[str, Any]]:
    qs = base_qs if base_qs is not None else dashboards_queryset_for_user(user, company)
    filters: list[dict[str, Any]] = []
    can_review = has_review_perm(user, company, template_code)
    can_assign = has_assign_viewers_perm(user, company, template_code)
    can_upload = has_upload_perm(user, company, template_code)

    def add(key: str, label_key: str, count_qs: QuerySet[Dashboard]) -> None:
        count = count_qs.count()
        if count > 0 or key == FILTER_ALL:
            filters.append({"key": key, "label_key": label_key, "count": count})

    add(FILTER_ALL, "dl_filter_all", qs)

    if can_review:
        pending = qs.filter(status=DashboardStatus.UNDER_REVIEW)
        if pending.exists() or len(filters) > 1:
            filters.append(
                {
                    "key": FILTER_PENDING_REVIEW,
                    "label_key": "dl_filter_pending_review",
                    "count": pending.count(),
                }
            )

    show_published_filter = (
        can_review
        or can_assign
        or user_has_dashboard_viewer_grant(user, company, template_code)
    )
    if show_published_filter:
        published = qs.filter(status=DashboardStatus.PUBLISHED)
        if published.exists() or (can_review and len(filters) > 1):
            filters.append(
                {
                    "key": FILTER_PUBLISHED,
                    "label_key": "dl_filter_published",
                    "count": published.count(),
                }
            )

    mine = qs.filter(created_by=user)
    if mine.exists() and (can_upload or can_review):
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

    if user.is_superuser:
        drafts = qs.filter(status=DashboardStatus.DRAFT)
        if drafts.exists():
            filters.append(
                {
                    "key": FILTER_DRAFT,
                    "label_key": "dl_filter_draft",
                    "count": drafts.count(),
                }
            )

    if len(filters) <= 1:
        return []
    return filters


def deleted_dashboards_queryset_for_user(user, company: Company | None = None) -> QuerySet[Dashboard]:
    """Deleted dashboards are visible only in Django admin (deleted filter)."""
    return Dashboard.objects.none()


def get_dashboard_for_review(user, pk: int, company: Company | None = None) -> Dashboard | None:
    try:
        dashboard = Dashboard.objects.select_related(
            "created_by",
            "upload_session",
            "reviewed_by",
            "company",
        ).get(pk=pk, is_deleted=False)
    except Dashboard.DoesNotExist:
        return None
    if not has_review_perm(user, company or dashboard.company, dashboard.template_type):
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
        ).get(pk=pk)
    except Dashboard.DoesNotExist:
        return None
    if dashboard.is_deleted:
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
        Dashboard.objects.filter(pk=pk, is_deleted=False)
        .values_list("company_id", flat=True)
        .first()
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
        ).get(pk=pk)
    except Dashboard.DoesNotExist:
        return None
    if dashboard.is_deleted:
        return None
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
        and has_upload_perm(user, active, dashboard.template_type)
        and _uses_v2(active)
        and (active is None or dashboard.company_id == active.id or user.is_superuser)
    )


def submit_dashboard(user, dashboard: Dashboard, company: Company | None = None) -> None:
    if not can_user_submit(user, dashboard, company):
        raise PermissionError("submit_forbidden")
    submit_dashboard_for_review(dashboard)


def approve_dashboard(dashboard: Dashboard, reviewer) -> str:
    """Publish dashboard after reviewer approval."""
    publish_dashboard(dashboard, reviewer)
    return "published"


def reject_dashboard(dashboard: Dashboard, reviewer, reason: str) -> DashboardRejectionLog:
    DashboardViewer.objects.filter(dashboard=dashboard).delete()
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


@transaction.atomic
def return_published_to_review(dashboard: Dashboard, reviewer) -> None:
    """Move a published dashboard back to pending approval/rejection."""
    DashboardViewer.objects.filter(dashboard=dashboard).delete()
    dashboard.status = DashboardStatus.UNDER_REVIEW
    dashboard.published_at = None
    dashboard.submitted_at = timezone.now()
    dashboard.reviewed_by = reviewer
    dashboard.save(
        update_fields=["status", "published_at", "submitted_at", "reviewed_by"]
    )


def mark_dashboard_draft(dashboard: Dashboard) -> None:
    DashboardViewer.objects.filter(dashboard=dashboard).delete()
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
        and has_upload_perm(user, active, dashboard.template_type)
        and (active is None or dashboard.company_id == active.id or user.is_superuser)
    )


def can_user_save_dashboard_user_edits(
    user,
    dashboard: Dashboard,
    company: Company | None = None,
) -> bool:
    """Allow persisting audit-plan / review-note edits until publish."""
    if dashboard.is_deleted or dashboard.status == DashboardStatus.PUBLISHED:
        return False
    return user_can_see_dashboard(user, dashboard, company)


def can_user_manage_review_attachments(
    user,
    dashboard: Dashboard,
    company: Company | None = None,
) -> bool:
    """Reviewer may add/replace/remove deck attachments while pending approval."""
    return (
        can_user_review(user, dashboard, company)
        and dashboard.status == DashboardStatus.UNDER_REVIEW
    )


def can_user_review(user, dashboard: Dashboard, company: Company | None = None) -> bool:
    active = company or dashboard.company
    if not has_review_perm(user, active, dashboard.template_type) or dashboard.is_deleted:
        return False
    if active is not None and dashboard.company_id != active.id and not user.is_superuser:
        return False

    company_v2 = _uses_v2(active)
    if company_v2:
        return dashboard.status in _REVIEWABLE_STATUSES
    return dashboard.status == DashboardStatus.DRAFT


def can_user_return_published_to_review(
    user,
    dashboard: Dashboard,
    company: Company | None = None,
) -> bool:
    """Reviewer may return a published dashboard to pending approval/rejection."""
    active = company or dashboard.company
    if not has_review_perm(user, active, dashboard.template_type) or dashboard.is_deleted:
        return False
    if active is not None and dashboard.company_id != active.id and not user.is_superuser:
        return False
    if not _uses_v2(active):
        return False
    return dashboard.status == DashboardStatus.PUBLISHED


def return_published_dashboard_to_review(
    user,
    dashboard: Dashboard,
    company: Company | None = None,
) -> None:
    if not can_user_return_published_to_review(user, dashboard, company):
        raise PermissionError("return_to_review_forbidden")
    return_published_to_review(dashboard, reviewer=user)


def can_user_manage_dashboard_viewers(
    user,
    dashboard: Dashboard,
    company: Company | None = None,
) -> bool:
    active = company or dashboard.company
    if dashboard.is_deleted or dashboard.status != DashboardStatus.PUBLISHED:
        return False
    if not has_assign_viewers_perm(user, active, dashboard.template_type):
        return False
    if active is not None and dashboard.company_id != active.id and not user.is_superuser:
        return False
    return True


def company_members_for_viewer_assignment(
    company: Company,
    dashboard: Dashboard | None = None,
) -> QuerySet[User]:
    """
    Company members eligible to receive a per-dashboard viewer grant.

    Excludes users who already see published dashboards without a grant:
    superusers, dashboard creator, reviewers, and assign-viewers managers.
    """
    user_ids = CompanyMembership.objects.filter(
        company=company,
        is_deleted=False,
    ).values_list("user_id", flat=True)
    qs = User.objects.filter(pk__in=user_ids, is_active=True).order_by("username")
    if dashboard is None:
        return qs

    exclude_ids: set[int] = set(
        User.objects.filter(is_superuser=True).values_list("pk", flat=True)
    )
    if dashboard.created_by_id:
        exclude_ids.add(dashboard.created_by_id)

    privileged_ids = CompanyMembershipTemplateAccess.objects.filter(
        membership__company=company,
        membership__is_deleted=False,
        template_code=dashboard.template_type,
    ).filter(
        Q(can_assign_dashboard_viewers=True) | Q(can_review=True)
    ).values_list("membership__user_id", flat=True)
    exclude_ids.update(privileged_ids)

    if exclude_ids:
        qs = qs.exclude(pk__in=exclude_ids)
    return qs


def get_dashboard_viewer_user_ids(dashboard: Dashboard) -> set[int]:
    return set(
        DashboardViewer.objects.filter(dashboard=dashboard).values_list(
            "user_id", flat=True
        )
    )


def get_dashboard_viewer_attachment_map(dashboard: Dashboard) -> dict[int, list[str]]:
    """Return {user_id: allowed_attachment_kinds} for assigned viewers."""
    result: dict[int, list[str]] = {}
    for user_id, kinds in DashboardViewer.objects.filter(
        dashboard=dashboard
    ).values_list("user_id", "allowed_attachment_kinds"):
        if isinstance(kinds, list):
            result[user_id] = [str(k) for k in kinds]
        else:
            result[user_id] = []
    return result


def normalize_viewer_attachment_kinds(
    kinds: list[str] | None,
    company: Company | None,
) -> list[str]:
    """Keep only valid, company-enabled attachment kinds (stable order)."""
    enabled = get_enabled_attachment_kinds(company)
    valid = set(ATTACHMENT_KIND_CODES) & enabled
    seen: set[str] = set()
    out: list[str] = []
    for kind in kinds or []:
        code = str(kind).strip()
        if code in valid and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def user_allowed_attachment_kinds(
    user,
    dashboard: Dashboard,
    company: Company | None = None,
) -> set[str] | None:
    """
    Attachment kinds the user may see on this dashboard.

    Returns None when unrestricted (creator, reviewer, assigner, superuser).
    Returns a set (possibly empty) for assigned-only viewers.
    """
    if user.is_superuser:
        return None

    active = company or dashboard.company

    if user_is_creator(user, dashboard):
        return None

    if has_review_perm(user, active, dashboard.template_type):
        return None

    if has_assign_viewers_perm(user, active, dashboard.template_type):
        return None

    grant = (
        DashboardViewer.objects.filter(dashboard=dashboard, user=user)
        .values_list("allowed_attachment_kinds", flat=True)
        .first()
    )
    if grant is None:
        # Can see dashboard by some other path with no grant row — unrestricted.
        return None
    if not isinstance(grant, list):
        return set()
    enabled = get_enabled_attachment_kinds(active)
    return {str(k) for k in grant if str(k) in enabled}


@transaction.atomic
def set_dashboard_viewers(
    dashboard: Dashboard,
    user_ids: list[int],
    granted_by: User,
    attachment_kinds_by_user: dict[int, list[str]] | None = None,
) -> tuple[set[int], set[int]]:
    """
    Replace viewer assignments for a published dashboard.

    ``attachment_kinds_by_user`` maps user_id → allowed attachment kind codes.
    New viewers default to no attachment kinds when omitted.
    Existing viewers keep prior kinds when omitted from the map.

    Returns (added_user_ids, removed_user_ids).
    """
    company = dashboard.company
    if company is None:
        raise ValueError("no_company")

    allowed_ids = set(
        company_members_for_viewer_assignment(
            company,
            dashboard=dashboard,
        ).values_list("pk", flat=True)
    )
    # Keep currently assigned viewers even if they later gained privileged access,
    # so the assigner can still remove them explicitly.
    allowed_ids |= get_dashboard_viewer_user_ids(dashboard)
    requested = {uid for uid in user_ids if uid in allowed_ids}
    current = get_dashboard_viewer_user_ids(dashboard)
    kinds_map = attachment_kinds_by_user or {}

    to_add = requested - current
    to_remove = current - requested
    to_keep = requested & current

    if to_remove:
        DashboardViewer.objects.filter(
            dashboard=dashboard,
            user_id__in=to_remove,
        ).delete()

    if to_add:
        DashboardViewer.objects.bulk_create(
            [
                DashboardViewer(
                    dashboard=dashboard,
                    user_id=uid,
                    granted_by=granted_by,
                    allowed_attachment_kinds=normalize_viewer_attachment_kinds(
                        kinds_map.get(uid, []),
                        company,
                    ),
                )
                for uid in to_add
            ],
            ignore_conflicts=True,
        )

    for uid in to_keep:
        if uid not in kinds_map:
            continue
        normalized = normalize_viewer_attachment_kinds(kinds_map[uid], company)
        DashboardViewer.objects.filter(dashboard=dashboard, user_id=uid).update(
            allowed_attachment_kinds=normalized,
        )

    return to_add, to_remove


def can_user_reject(user, dashboard: Dashboard, company: Company | None = None) -> bool:
    return can_user_review(user, dashboard, company)


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
