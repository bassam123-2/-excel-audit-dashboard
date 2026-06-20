"""Workflow template versioning — one active template per company."""
from __future__ import annotations

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Max
from django.utils.translation import gettext_lazy as _

from audit_app.models import Company, WorkflowTemplate, WorkflowTemplateStep


class WorkflowTemplateError(Exception):
    """Raised when workflow template rules are violated."""


def next_workflow_version(company: Company) -> int:
    current = (
        WorkflowTemplate.objects.filter(company=company).aggregate(max_v=Max("version"))[
            "max_v"
        ]
        or 0
    )
    return int(current) + 1


def company_has_workflow(company: Company) -> bool:
    return WorkflowTemplate.objects.filter(company=company, is_deleted=False).exists()


def get_active_workflow_template(company: Company) -> WorkflowTemplate | None:
    return (
        WorkflowTemplate.objects.filter(
            company=company,
            is_active=True,
            is_deleted=False,
        )
        .order_by("-version")
        .first()
    )


def deactivate_company_workflows(company: Company) -> None:
    WorkflowTemplate.objects.filter(company=company, is_active=True).update(
        is_active=False
    )


@transaction.atomic
def create_initial_workflow_template(
    company: Company,
    *,
    name: str,
    steps: list[tuple[int, User]],
) -> WorkflowTemplate:
    if company_has_workflow(company):
        raise WorkflowTemplateError(
            _("This company already has a workflow. Edit the active version to publish changes.")
        )
    template = WorkflowTemplate.objects.create(
        company=company,
        name=_workflow_template_name(company, name),
        version=1,
        is_active=True,
    )
    _replace_steps(template, steps)
    return template


@transaction.atomic
def create_workflow_template_revision(
    source: WorkflowTemplate,
    *,
    name: str,
    steps: list[tuple[int, User]],
) -> WorkflowTemplate:
    if not source.is_active:
        raise WorkflowTemplateError(
            _("Only the active workflow can be edited. Historical versions are read-only.")
        )
    company = source.company
    deactivate_company_workflows(company)
    template = WorkflowTemplate.objects.create(
        company=company,
        name=_workflow_template_name(company, name or source.name),
        version=next_workflow_version(company),
        is_active=True,
    )
    _replace_steps(template, steps)
    return template


def _workflow_template_name(company: Company, name: str | None) -> str:
    """Internal label — one template per company; defaults to company code."""
    cleaned = (name or company.code or "Default").strip()
    return cleaned or company.code or "Default"


def _replace_steps(template: WorkflowTemplate, steps: list[tuple[int, User]]) -> None:
    """Persist steps in listed order with sequential step_order 1..N."""
    assignees = [assignee for _, assignee in steps if assignee is not None]
    if not assignees:
        WorkflowTemplateStep.objects.filter(template=template).delete()
        return
    WorkflowTemplateStep.objects.filter(template=template).delete()
    WorkflowTemplateStep.objects.bulk_create(
        [
            WorkflowTemplateStep(
                template=template,
                step_order=index,
                assignee=assignee,
            )
            for index, assignee in enumerate(assignees, start=1)
        ]
    )
