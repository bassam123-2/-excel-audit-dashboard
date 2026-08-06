"""API tests for per-dashboard viewer assignment."""
from __future__ import annotations

import json

from django.contrib.auth.models import User
from django.test import Client, TestCase

from audit_app.models import (
    Company,
    CompanyMembership,
    Dashboard,
    DashboardStatus,
    DashboardViewer,
)


class DashboardViewersApiTests(TestCase):
    def setUp(self):
        self.company, _ = Company.objects.get_or_create(
            code="BTC",
            defaults={"name": "BTC", "excel_company_names": ["BTC"]},
        )
        self.company.ensure_attachment_settings()
        self.assigner = self._user("dv_assigner", "assigner@example.com")
        self.viewer = self._user("dv_viewer", "viewer@example.com")
        self.creator = self._user("dv_creator", "creator@example.com")

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
            name="Published Dash",
            report_id="rid-dv-api-1",
            company=self.company,
            created_by=self.creator,
            status=DashboardStatus.PUBLISHED,
        )

        self.client = Client()
        self.client.post("/login/", {"username": "dv_assigner", "password": "Test@1234"})
        self.client.post("/select-company/", {"company_id": self.company.pk})

    def _user(self, username: str, email: str) -> User:
        user = User.objects.create_user(username, password="Test@1234", email=email)
        profile = user.profile
        profile.two_factor_enabled = False
        profile.save(update_fields=["two_factor_enabled"])
        return user

    def test_get_viewers_lists_company_members(self):
        response = self.client.get(
            f"/dashboards/{self.dashboard.pk}/viewers/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        member_ids = {item["id"] for item in data["members"]}
        self.assertIn(self.viewer.pk, member_ids)
        # Creator / assigners already access published dashboards without a grant.
        self.assertNotIn(self.creator.pk, member_ids)
        self.assertNotIn(self.assigner.pk, member_ids)
        self.assertIn("attachment_kind_options", data)
        self.assertTrue(any(o["kind"] == "deck" for o in data["attachment_kind_options"]))

    def test_get_viewers_excludes_superuser_and_reviewer(self):
        superuser = self._user("dv_super", "super@example.com")
        superuser.is_superuser = True
        superuser.save(update_fields=["is_superuser"])
        CompanyMembership.objects.create(user=superuser, company=self.company)

        reviewer = self._user("dv_reviewer", "reviewer@example.com")
        CompanyMembership.objects.create(
            user=reviewer,
            company=self.company,
            can_review=True,
        )

        response = self.client.get(
            f"/dashboards/{self.dashboard.pk}/viewers/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        member_ids = {item["id"] for item in response.json()["members"]}
        self.assertNotIn(superuser.pk, member_ids)
        self.assertNotIn(reviewer.pk, member_ids)
        self.assertIn(self.viewer.pk, member_ids)

    def test_post_viewers_saves_assignments(self):
        response = self.client.post(
            f"/dashboards/{self.dashboard.pk}/viewers/",
            data={"user_ids": [self.viewer.pk]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        grant = DashboardViewer.objects.get(
            dashboard=self.dashboard,
            user=self.viewer,
        )
        self.assertEqual(grant.allowed_attachment_kinds, [])

    def test_post_assignments_with_attachment_kinds(self):
        payload = json.dumps(
            [
                {
                    "user_id": self.viewer.pk,
                    "attachment_kinds": ["deck", "highRisk"],
                }
            ]
        )
        response = self.client.post(
            f"/dashboards/{self.dashboard.pk}/viewers/",
            data={"assignments": payload},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        grant = DashboardViewer.objects.get(
            dashboard=self.dashboard,
            user=self.viewer,
        )
        self.assertEqual(grant.allowed_attachment_kinds, ["deck", "highRisk"])

        get_resp = self.client.get(
            f"/dashboards/{self.dashboard.pk}/viewers/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        member = next(
            m for m in get_resp.json()["members"] if m["id"] == self.viewer.pk
        )
        self.assertTrue(member["assigned"])
        self.assertEqual(member["attachment_kinds"], ["deck", "highRisk"])

    def test_post_assignments_can_update_kinds(self):
        DashboardViewer.objects.create(
            dashboard=self.dashboard,
            user=self.viewer,
            granted_by=self.assigner,
            allowed_attachment_kinds=["deck"],
        )
        payload = json.dumps(
            [{"user_id": self.viewer.pk, "attachment_kinds": ["highRisk"]}]
        )
        response = self.client.post(
            f"/dashboards/{self.dashboard.pk}/viewers/",
            data={"assignments": payload},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        grant = DashboardViewer.objects.get(
            dashboard=self.dashboard,
            user=self.viewer,
        )
        self.assertEqual(grant.allowed_attachment_kinds, ["highRisk"])

    def test_forbidden_for_user_without_assign_perm(self):
        client = Client()
        client.post("/login/", {"username": "dv_viewer", "password": "Test@1234"})
        client.post("/select-company/", {"company_id": self.company.pk})
        response = client.get(
            f"/dashboards/{self.dashboard.pk}/viewers/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 403)

    def test_forbidden_when_not_published(self):
        draft = Dashboard.objects.create(
            name="Draft",
            report_id="rid-dv-draft",
            company=self.company,
            created_by=self.creator,
            status=DashboardStatus.DRAFT,
        )
        response = self.client.get(
            f"/dashboards/{draft.pk}/viewers/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 403)
