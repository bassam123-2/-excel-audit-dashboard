"""Dashboard submit and publish workflow."""
from __future__ import annotations

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from audit_app.models import Company, Dashboard, DashboardStatus


def company_uses_workflow_v2(company: Company | None) -> bool:
    if company is None:
        return True
    return bool(company.use_workflow_v2)


@transaction.atomic
def submit_dashboard_for_review(dashboard: Dashboard) -> None:
    dashboard.status = DashboardStatus.UNDER_REVIEW
    dashboard.submitted_at = timezone.now()
    dashboard.save(update_fields=["status", "submitted_at"])


@transaction.atomic
def publish_dashboard(dashboard: Dashboard, reviewer: User | None = None) -> None:
    dashboard.status = DashboardStatus.PUBLISHED
    dashboard.published_at = timezone.now()
    if reviewer is not None:
        dashboard.reviewed_by = reviewer
    dashboard.save(update_fields=["status", "published_at", "reviewed_by"])
