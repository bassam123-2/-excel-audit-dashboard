"""Admin tests for workflow template versioning."""
from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from audit_app.admin_utils import WorkflowAssigneeAutocompleteWidget
from audit_app.models import Company, WorkflowTemplate, WorkflowTemplateStep


class WorkflowTemplateAdminTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            code="ADM",
            name="Admin WF Co",
            excel_company_names=["ADM"],
        )
        self.other_company = Company.objects.create(
            code="OTH",
            name="Other Co",
            excel_company_names=["OTH"],
        )
        self.admin = User.objects.create_superuser(
            "wf_admin",
            "wf_admin@example.com",
            "Test@1234",
        )
        self.assignee = User.objects.create_user(
            "wf_step_user",
            password="Test@1234",
            email="step@example.com",
            first_name="Step",
            last_name="User",
        )
        self.template = WorkflowTemplate.objects.create(
            company=self.company,
            name="ADM",
            version=1,
            is_active=True,
        )
        WorkflowTemplateStep.objects.create(
            template=self.template,
            step_order=1,
            assignee=self.assignee,
        )
        self.client = Client()
        self.client.force_login(self.admin)

    def test_assignee_widget_build_attrs(self):
        db_field = WorkflowTemplateStep._meta.get_field("assignee")
        widget = WorkflowAssigneeAutocompleteWidget(db_field, admin.site)
        attrs = widget.build_attrs({})
        self.assertIn("wf-assignee-autocomplete", attrs["class"])
        self.assertNotIn("admin-autocomplete", attrs["class"].split())
        self.assertEqual(attrs["data-ajax--cache"], "false")

    def test_change_creates_new_version_without_formset_error(self):
        assignee_b = User.objects.create_user(
            "wf_step_user_b",
            password="Test@1234",
            email="b@example.com",
        )
        url = reverse("admin:audit_app_workflowtemplate_change", args=[self.template.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        prefix = "steps"
        post_data = {
            "company": self.company.pk,
            "version": "1",
            "is_active": "on",
            "_save": "Save",
            f"{prefix}-TOTAL_FORMS": "2",
            f"{prefix}-INITIAL_FORMS": "1",
            f"{prefix}-MIN_NUM_FORMS": "0",
            f"{prefix}-MAX_NUM_FORMS": "1000",
            f"{prefix}-0-id": str(self.template.steps.first().pk),
            f"{prefix}-0-template": str(self.template.pk),
            f"{prefix}-0-assignee": str(self.assignee.pk),
            f"{prefix}-1-template": str(self.template.pk),
            f"{prefix}-1-assignee": str(assignee_b.pk),
        }
        response = self.client.post(url, post_data, follow=False)
        self.assertEqual(response.status_code, 302, msg=response.content.decode()[:2000])
        new_active = WorkflowTemplate.objects.get(company=self.company, is_active=True)
        orders = list(new_active.steps.order_by("step_order").values_list("step_order", flat=True))
        self.assertEqual(orders, [1, 2])

    def test_save_applies_submitted_form_row_order(self):
        assignee_b = User.objects.create_user(
            "wf_step_user_b",
            password="Test@1234",
            email="b@example.com",
        )
        url = reverse("admin:audit_app_workflowtemplate_change", args=[self.template.pk])
        prefix = "steps"
        post_data = {
            "company": self.company.pk,
            "version": "1",
            "is_active": "on",
            "_save": "Save",
            f"{prefix}-TOTAL_FORMS": "2",
            f"{prefix}-INITIAL_FORMS": "1",
            f"{prefix}-MIN_NUM_FORMS": "0",
            f"{prefix}-MAX_NUM_FORMS": "1000",
            f"{prefix}-0-id": str(self.template.steps.first().pk),
            f"{prefix}-0-template": str(self.template.pk),
            f"{prefix}-0-assignee": str(assignee_b.pk),
            f"{prefix}-0-wf_row_order": "0",
            f"{prefix}-1-template": str(self.template.pk),
            f"{prefix}-1-assignee": str(self.assignee.pk),
            f"{prefix}-1-wf_row_order": "1",
        }
        response = self.client.post(url, post_data, follow=False)
        self.assertEqual(response.status_code, 302, msg=response.content.decode()[:2000])
        new_active = WorkflowTemplate.objects.get(company=self.company, is_active=True)
        assignee_order = list(
            new_active.steps.order_by("step_order").values_list("assignee_id", flat=True)
        )
        self.assertEqual(assignee_order, [assignee_b.pk, self.assignee.pk])

    def test_save_applies_wf_row_order_when_form_indices_unchanged(self):
        """Simulates drag-reorder: DOM order differs from original form indices."""
        assignee_b = User.objects.create_user(
            "wf_step_user_b2",
            password="Test@1234",
            email="b2@example.com",
        )
        url = reverse("admin:audit_app_workflowtemplate_change", args=[self.template.pk])
        prefix = "steps"
        post_data = {
            "company": self.company.pk,
            "version": "1",
            "is_active": "on",
            "_save": "Save",
            f"{prefix}-TOTAL_FORMS": "2",
            f"{prefix}-INITIAL_FORMS": "1",
            f"{prefix}-MIN_NUM_FORMS": "0",
            f"{prefix}-MAX_NUM_FORMS": "1000",
            f"{prefix}-0-id": str(self.template.steps.first().pk),
            f"{prefix}-0-template": str(self.template.pk),
            f"{prefix}-0-assignee": str(self.assignee.pk),
            f"{prefix}-0-wf_row_order": "1",
            f"{prefix}-1-template": str(self.template.pk),
            f"{prefix}-1-assignee": str(assignee_b.pk),
            f"{prefix}-1-wf_row_order": "0",
        }
        response = self.client.post(url, post_data, follow=False)
        self.assertEqual(response.status_code, 302, msg=response.content.decode()[:2000])
        new_active = WorkflowTemplate.objects.get(company=self.company, is_active=True)
        assignee_order = list(
            new_active.steps.order_by("step_order").values_list("assignee_id", flat=True)
        )
        self.assertEqual(assignee_order, [assignee_b.pk, self.assignee.pk])

    def test_duplicate_assignee_is_rejected(self):
        url = reverse("admin:audit_app_workflowtemplate_change", args=[self.template.pk])
        prefix = "steps"
        post_data = {
            "company": self.company.pk,
            "version": "1",
            "is_active": "on",
            "_save": "Save",
            f"{prefix}-TOTAL_FORMS": "2",
            f"{prefix}-INITIAL_FORMS": "1",
            f"{prefix}-MIN_NUM_FORMS": "0",
            f"{prefix}-MAX_NUM_FORMS": "1000",
            f"{prefix}-0-id": str(self.template.steps.first().pk),
            f"{prefix}-0-template": str(self.template.pk),
            f"{prefix}-0-assignee": str(self.assignee.pk),
            f"{prefix}-1-template": str(self.template.pk),
            f"{prefix}-1-assignee": str(self.assignee.pk),
        }
        response = self.client.post(url, post_data, follow=False)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Each person can appear only once in the workflow chain.",
        )

    def test_changelist_defaults_to_active_only(self):
        inactive = WorkflowTemplate.objects.create(
            company=self.other_company,
            name="OTH",
            version=1,
            is_active=False,
        )
        url = reverse("admin:audit_app_workflowtemplate_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(f"workflowtemplate/{self.template.pk}/change/", content)
        self.assertNotIn(f"workflowtemplate/{inactive.pk}/change/", content)

    def test_changelist_inactive_filter_shows_historical_versions(self):
        inactive = WorkflowTemplate.objects.create(
            company=self.other_company,
            name="OTH",
            version=1,
            is_active=False,
        )
        url = reverse("admin:audit_app_workflowtemplate_changelist")
        response = self.client.get(url, {"is_active": "0"})
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(f"workflowtemplate/{inactive.pk}/change/", content)
        self.assertNotIn(f"workflowtemplate/{self.template.pk}/change/", content)

    def test_add_form_excludes_companies_with_existing_template(self):
        url = reverse("admin:audit_app_workflowtemplate_add")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(f'<option value="{self.other_company.pk}"', content)
        self.assertNotIn(f'<option value="{self.company.pk}"', content)

    def test_change_form_shows_username_and_full_name(self):
        url = reverse("admin:audit_app_workflowtemplate_change", args=[self.template.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "wf_step_user - Step User")

    def test_assignee_autocomplete_shows_full_name(self):
        other = User.objects.create_user(
            "wf_other",
            password="Test@1234",
            email="other@example.com",
            first_name="Other",
            last_name="Person",
        )
        url = reverse("admin:audit_app_workflowtemplate_assignee_autocomplete")
        response = self.client.get(url, {"term": "wf_"})
        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        labels = {item["id"]: item["text"] for item in results}
        self.assertEqual(labels[str(other.pk)], "wf_other - Other Person")

    def test_assignee_autocomplete_excludes_already_selected(self):
        url = reverse("admin:audit_app_workflowtemplate_assignee_autocomplete")
        response = self.client.get(
            url,
            {
                "term": "wf_",
                "exclude_assignees": str(self.assignee.pk),
            },
        )
        self.assertEqual(response.status_code, 200)
        result_ids = {item["id"] for item in response.json()["results"]}
        self.assertNotIn(str(self.assignee.pk), result_ids)
