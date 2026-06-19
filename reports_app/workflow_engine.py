"""Multi-step acknowledgment workflow before dashboard publish."""
from __future__ import annotations

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from audit_app.models import (
    Company,
    Dashboard,
    DashboardStatus,
    DashboardWorkflowInstance,
    DashboardWorkflowStepLog,
    DashboardWorkflowStepSnapshot,
    WorkflowTemplate,
    WorkflowTemplateStep,
)


def company_uses_workflow_v2(company: Company | None) -> bool:
    if company is None:
        return True
    return bool(company.use_workflow_v2)


def get_active_workflow_template(company: Company) -> WorkflowTemplate | None:
    from audit_app.workflow_template_service import get_active_workflow_template as _get

    return _get(company)


def template_has_steps(template: WorkflowTemplate | None) -> bool:
    if template is None:
        return False
    return template.steps.exists()


def get_workflow_instance(dashboard: Dashboard) -> DashboardWorkflowInstance | None:
    return getattr(dashboard, "workflow_instance", None)


def workflow_progress_label(dashboard: Dashboard) -> str | None:
    instance = get_workflow_instance(dashboard)
    if not instance or instance.total_steps <= 0:
        return None
    current = min(instance.current_step_index + 1, instance.total_steps)
    return f"{current}/{instance.total_steps}"


def current_assignee_display(dashboard: Dashboard) -> str:
    instance = get_workflow_instance(dashboard)
    if instance and instance.current_assignee_id:
        user = instance.current_assignee
        full = user.get_full_name().strip()
        return full or user.username
    return ""


def _cancel_workflow_instance(dashboard: Dashboard) -> None:
    instance = get_workflow_instance(dashboard)
    if instance is not None:
        instance.delete()


@transaction.atomic
def submit_dashboard_for_review(dashboard: Dashboard) -> None:
    dashboard.status = DashboardStatus.UNDER_REVIEW
    dashboard.submitted_at = timezone.now()
    dashboard.save(update_fields=["status", "submitted_at"])


@transaction.atomic
def start_workflow_after_approval(dashboard: Dashboard, reviewer: User) -> bool:
    """
    Start acknowledgment chain after reviewer approval.

    Returns True if workflow started (status=in_workflow), False if published directly.
    """
    company = dashboard.company
    if company is None or not company_uses_workflow_v2(company):
        return False

    template = get_active_workflow_template(company)
    steps = list(
        WorkflowTemplateStep.objects.filter(template=template)
        .select_related("assignee")
        .order_by("step_order")
    )
    if not steps:
        return False

    _cancel_workflow_instance(dashboard)

    instance = DashboardWorkflowInstance.objects.create(
        dashboard=dashboard,
        template_version=template.version if template else 1,
        current_step_index=0,
        total_steps=len(steps),
        current_assignee=steps[0].assignee,
    )
    snapshots = [
        DashboardWorkflowStepSnapshot(
            instance=instance,
            step_order=step.step_order,
            assignee=step.assignee,
        )
        for step in steps
    ]
    DashboardWorkflowStepSnapshot.objects.bulk_create(snapshots)

    dashboard.status = DashboardStatus.IN_WORKFLOW
    dashboard.reviewed_by = reviewer
    dashboard.save(update_fields=["status", "reviewed_by"])
    return True


@transaction.atomic
def publish_dashboard(dashboard: Dashboard, reviewer: User | None = None) -> None:
    instance = get_workflow_instance(dashboard)
    if instance and not instance.is_complete:
        instance.is_complete = True
        instance.completed_at = timezone.now()
        instance.current_assignee = None
        instance.save(
            update_fields=["is_complete", "completed_at", "current_assignee"]
        )

    dashboard.status = DashboardStatus.PUBLISHED
    dashboard.published_at = timezone.now()
    if reviewer is not None:
        dashboard.reviewed_by = reviewer
    dashboard.save(update_fields=["status", "published_at", "reviewed_by"])


@transaction.atomic
def acknowledge_workflow_step(dashboard: Dashboard, user: User) -> bool:
    """
    Record acknowledgment and advance workflow.

    Returns True if dashboard was published (workflow complete).
    """
    instance = get_workflow_instance(dashboard)
    if instance is None or dashboard.status != DashboardStatus.IN_WORKFLOW:
        raise ValueError("not_in_workflow")
    if instance.current_assignee_id != user.id:
        raise ValueError("not_current_assignee")

    snapshots = list(instance.step_snapshots.order_by("step_order"))
    if instance.current_step_index >= len(snapshots):
        raise ValueError("invalid_step")

    current_snapshot = snapshots[instance.current_step_index]
    DashboardWorkflowStepLog.objects.create(
        instance=instance,
        step_order=current_snapshot.step_order,
        assignee=current_snapshot.assignee,
        acknowledged_by=user,
    )

    next_index = instance.current_step_index + 1
    if next_index >= len(snapshots):
        publish_dashboard(dashboard)
        return True

    next_snapshot = snapshots[next_index]
    instance.current_step_index = next_index
    instance.current_assignee = next_snapshot.assignee
    instance.save(update_fields=["current_step_index", "current_assignee"])
    return False


def cancel_workflow_on_reject(dashboard: Dashboard) -> None:
    _cancel_workflow_instance(dashboard)
