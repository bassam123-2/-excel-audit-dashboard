"""Server-rendered viewer + attachment kind assignment page."""
from __future__ import annotations

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from audit_app.models import (
    Company,
    CompanyMembership,
    Dashboard,
    DashboardStatus,
    DashboardViewer,
)


class DashboardViewersManageTests(TestCase):
    def setUp(self):
        self.company, _ = Company.objects.get_or_create(
            code="BTC",
            defaults={"name": "BTC", "excel_company_names": ["BTC"]},
        )
        self.company.ensure_attachment_settings()
        self.assigner = self._user("dvm_assigner", "dvm_assigner@example.com")
        self.viewer = self._user("dvm_viewer", "dvm_viewer@example.com")
        self.creator = self._user("dvm_creator", "dvm_creator@example.com")

        CompanyMembership.objects.create(
            user=self.assigner,
            company=self.company,
            can_assign_dashboard_viewers=True,
        )
        CompanyMembership.objects.create(user=self.viewer, company=self.company)
        CompanyMembership.objects.create(
            user=self.creator,
            company=self.company,
            can_upload=True,
        )

        self.dashboard = Dashboard.objects.create(
            name="Published Manage",
            report_id="rid-dvm-1",
            company=self.company,
            created_by=self.creator,
            status=DashboardStatus.PUBLISHED,
        )
        # Pre-existing grant (as on VPS before feature).
        DashboardViewer.objects.create(
            dashboard=self.dashboard,
            user=self.viewer,
            granted_by=self.assigner,
            allowed_attachment_kinds=["deck", "highRisk", "tgaViolations"],
        )

        self.client = Client()
        self.client.post("/login/", {"username": "dvm_assigner", "password": "Test@1234"})
        self.client.post("/select-company/", {"company_id": self.company.pk})

    def _user(self, username: str, email: str) -> User:
        user = User.objects.create_user(username, password="Test@1234", email=email)
        profile = user.profile
        profile.two_factor_enabled = False
        profile.save(update_fields=["two_factor_enabled"])
        return user

    def test_manage_page_shows_existing_viewer_and_kinds(self):
        url = reverse("dashboard_viewers_manage", args=[self.dashboard.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "dvm_viewer")
        self.assertContains(response, 'name="assigned"')
        self.assertContains(response, f'name="kinds_{self.viewer.pk}"')
        self.assertContains(response, 'value="deck"')

    def test_manage_page_can_restrict_attachments_for_existing_viewer(self):
        url = reverse("dashboard_viewers_manage", args=[self.dashboard.pk])
        response = self.client.post(
            url,
            data={
                "assigned": [str(self.viewer.pk)],
                f"kinds_{self.viewer.pk}": ["deck"],
            },
        )
        self.assertEqual(response.status_code, 302)
        grant = DashboardViewer.objects.get(
            dashboard=self.dashboard,
            user=self.viewer,
        )
        self.assertEqual(grant.allowed_attachment_kinds, ["deck"])

    def test_browser_get_viewers_api_redirects_to_manage_page(self):
        response = self.client.get(
            reverse("dashboard_viewers", args=[self.dashboard.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/viewers/manage/", response.url)

    def test_ajax_get_viewers_still_json(self):
        response = self.client.get(
            reverse("dashboard_viewers", args=[self.dashboard.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("attachment_kind_options", data)
        member = next(m for m in data["members"] if m["id"] == self.viewer.pk)
        self.assertTrue(member["assigned"])
