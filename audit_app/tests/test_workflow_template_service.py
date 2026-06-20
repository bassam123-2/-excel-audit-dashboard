"""Workflow template versioning tests."""
from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase

from audit_app.models import Company, WorkflowTemplate, WorkflowTemplateStep
from audit_app.workflow_template_service import (
    WorkflowTemplateError,
    company_has_workflow,
    create_initial_workflow_template,
    create_workflow_template_revision,
    get_active_workflow_template,
    next_workflow_version,
)


class WorkflowTemplateServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            code="WF",
            name="Workflow Co",
            excel_company_names=["WF"],
        )
        self.user_a = User.objects.create_user("wf_a", password="Test@1234", email="a@example.com")
        self.user_b = User.objects.create_user("wf_b", password="Test@1234", email="b@example.com")

    def test_initial_template_version_one_and_active(self):
        template = create_initial_workflow_template(
            self.company,
            name="Default",
            steps=[(1, self.user_a)],
        )
        self.assertEqual(template.version, 1)
        self.assertTrue(template.is_active)
        self.assertEqual(template.steps.count(), 1)

    def test_cannot_create_second_initial_template_for_same_company(self):
        create_initial_workflow_template(
            self.company,
            name="Default",
            steps=[(1, self.user_a)],
        )
        with self.assertRaises(WorkflowTemplateError):
            create_initial_workflow_template(
                self.company,
                name="Another",
                steps=[(1, self.user_b)],
            )

    def test_revision_increments_version_and_deactivates_old(self):
        first = create_initial_workflow_template(
            self.company,
            name="Default",
            steps=[(1, self.user_a)],
        )
        second = create_workflow_template_revision(
            first,
            name="Default",
            steps=[(1, self.user_a), (2, self.user_b)],
        )
        first.refresh_from_db()
        self.assertEqual(second.version, 2)
        self.assertTrue(second.is_active)
        self.assertFalse(first.is_active)
        self.assertEqual(second.steps.count(), 2)
        self.assertEqual(get_active_workflow_template(self.company).pk, second.pk)

    def test_cannot_edit_inactive_template(self):
        first = create_initial_workflow_template(
            self.company,
            name="Default",
            steps=[(1, self.user_a)],
        )
        create_workflow_template_revision(
            first,
            name="Default",
            steps=[(1, self.user_b)],
        )
        first.refresh_from_db()
        with self.assertRaises(WorkflowTemplateError):
            create_workflow_template_revision(
                first,
                name="Default",
                steps=[(1, self.user_a)],
            )

    def test_next_workflow_version_sequence(self):
        self.assertEqual(next_workflow_version(self.company), 1)
        create_initial_workflow_template(
            self.company,
            name="Default",
            steps=[(1, self.user_a)],
        )
        self.assertEqual(next_workflow_version(self.company), 2)
        self.assertTrue(company_has_workflow(self.company))

    def test_replace_steps_always_sequential(self):
        first = create_initial_workflow_template(
            self.company,
            name="Default",
            steps=[(1, self.user_a), (99, self.user_b)],
        )
        orders = list(first.steps.order_by("step_order").values_list("step_order", flat=True))
        self.assertEqual(orders, [1, 2])

    def test_active_query_returns_latest_revision(self):
        first = create_initial_workflow_template(
            self.company,
            name="Default",
            steps=[(1, self.user_a)],
        )
        second = create_workflow_template_revision(
            first,
            name="Default",
            steps=[(1, self.user_b)],
        )
        active = get_active_workflow_template(self.company)
        self.assertEqual(active.pk, second.pk)
        self.assertEqual(
            WorkflowTemplate.objects.filter(company=self.company, is_active=True).count(),
            1,
        )
