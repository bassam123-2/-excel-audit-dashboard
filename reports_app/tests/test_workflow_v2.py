"""Tests for dashboard workflow v2 (submit, publish, per-dashboard viewers)."""
from __future__ import annotations

from django.contrib.auth.models import User
from django.test import Client, TestCase

from audit_app.models import (
    Company,
    CompanyMembership,
    Dashboard,
    DashboardStatus,
    DashboardViewer,
)
from reports_app.dashboard_workflow import (
    FILTER_PENDING_REVIEW,
    approve_dashboard,
    available_dashboard_filters,
    can_user_delete_dashboard,
    can_user_manage_dashboard_viewers,
    can_user_return_published_to_review,
    can_user_review,
    can_user_submit,
    dashboards_queryset_for_user,
    filter_dashboards_queryset,
    reject_dashboard,
    return_published_dashboard_to_review,
    set_dashboard_viewers,
    submit_dashboard,
    user_allowed_attachment_kinds,
    user_can_see_dashboard,
)


class WorkflowV2Tests(TestCase):
    def setUp(self):
        self.company, _ = Company.objects.get_or_create(
            code="BTC",
            defaults={"name": "BTC", "excel_company_names": ["BTC"], "use_workflow_v2": True},
        )
        self.company.use_workflow_v2 = True
        self.company.save(update_fields=["use_workflow_v2"])

        self.creator = self._user("wf_creator", "creator@example.com")
        self.reviewer = self._user("wf_reviewer", "reviewer@example.com")
        self.viewer = self._user("wf_viewer", "viewer@example.com")
        self.assigner = self._user("wf_assigner", "assigner@example.com")

        CompanyMembership.objects.create(
            user=self.creator, company=self.company, can_upload=True
        )
        CompanyMembership.objects.create(
            user=self.reviewer,
            company=self.company,
            can_review=True,
        )
        CompanyMembership.objects.create(
            user=self.viewer, company=self.company
        )
        CompanyMembership.objects.create(
            user=self.assigner,
            company=self.company,
            can_assign_dashboard_viewers=True,
        )

    def _user(self, username: str, email: str) -> User:
        user = User.objects.create_user(username, password="Test@1234", email=email)
        profile = user.profile
        profile.two_factor_enabled = False
        profile.save(update_fields=["two_factor_enabled"])
        return user

    def _dashboard(self, *, status=DashboardStatus.DRAFT, creator=None) -> Dashboard:
        creator = creator or self.creator
        return Dashboard.objects.create(
            name=f"Dash-{status}",
            report_id=f"rid-{status}-{creator.username}-{Dashboard.objects.count()}",
            company=self.company,
            created_by=creator,
            status=status,
        )

    def test_reviewer_cannot_see_creator_draft(self):
        draft = self._dashboard(status=DashboardStatus.DRAFT)
        self.assertFalse(user_can_see_dashboard(self.reviewer, draft, self.company))

    def test_creator_sees_own_draft_and_rejected(self):
        draft = self._dashboard(status=DashboardStatus.DRAFT)
        rejected = self._dashboard(status=DashboardStatus.REJECTED)
        ids = set(
            dashboards_queryset_for_user(self.creator, self.company).values_list(
                "pk", flat=True
            )
        )
        self.assertIn(draft.pk, ids)
        self.assertIn(rejected.pk, ids)

    def test_submit_moves_to_under_review(self):
        draft = self._dashboard()
        self.assertTrue(can_user_submit(self.creator, draft, self.company))
        submit_dashboard(self.creator, draft, self.company)
        draft.refresh_from_db()
        self.assertEqual(draft.status, DashboardStatus.UNDER_REVIEW)
        self.assertIsNotNone(draft.submitted_at)
        self.assertTrue(user_can_see_dashboard(self.reviewer, draft, self.company))

    def test_approve_publishes_directly(self):
        dash = self._dashboard(status=DashboardStatus.UNDER_REVIEW)
        result = approve_dashboard(dash, self.reviewer)
        self.assertEqual(result, "published")
        dash.refresh_from_db()
        self.assertEqual(dash.status, DashboardStatus.PUBLISHED)
        self.assertIsNotNone(dash.published_at)

    def test_published_visible_only_to_assigned_viewers(self):
        dash = self._dashboard(status=DashboardStatus.PUBLISHED)
        self.assertFalse(user_can_see_dashboard(self.viewer, dash, self.company))
        DashboardViewer.objects.create(
            dashboard=dash,
            user=self.viewer,
            granted_by=self.assigner,
        )
        self.assertTrue(user_can_see_dashboard(self.viewer, dash, self.company))

    def test_reject_clears_viewer_assignments(self):
        dash = self._dashboard(status=DashboardStatus.PUBLISHED)
        DashboardViewer.objects.create(
            dashboard=dash,
            user=self.viewer,
            granted_by=self.assigner,
        )
        reject_dashboard(dash, self.reviewer, "Needs changes")
        self.assertFalse(DashboardViewer.objects.filter(dashboard=dash).exists())
        self.assertFalse(user_can_see_dashboard(self.viewer, dash, self.company))

    def test_set_dashboard_viewers(self):
        dash = self._dashboard(status=DashboardStatus.PUBLISHED)
        added, removed = set_dashboard_viewers(
            dash,
            [self.viewer.pk],
            granted_by=self.assigner,
        )
        self.assertEqual(added, {self.viewer.pk})
        self.assertEqual(removed, set())
        grant = DashboardViewer.objects.get(dashboard=dash, user=self.viewer)
        self.assertEqual(grant.allowed_attachment_kinds, [])

    def test_set_dashboard_viewers_with_attachment_kinds(self):
        self.company.ensure_attachment_settings()
        dash = self._dashboard(status=DashboardStatus.PUBLISHED)
        set_dashboard_viewers(
            dash,
            [self.viewer.pk],
            granted_by=self.assigner,
            attachment_kinds_by_user={self.viewer.pk: ["deck", "highRisk"]},
        )
        grant = DashboardViewer.objects.get(dashboard=dash, user=self.viewer)
        self.assertEqual(grant.allowed_attachment_kinds, ["deck", "highRisk"])

    def test_user_allowed_attachment_kinds_roles(self):
        self.company.ensure_attachment_settings()
        dash = self._dashboard(status=DashboardStatus.PUBLISHED)
        DashboardViewer.objects.create(
            dashboard=dash,
            user=self.viewer,
            granted_by=self.assigner,
            allowed_attachment_kinds=["deck"],
        )
        self.assertIsNone(
            user_allowed_attachment_kinds(self.creator, dash, self.company)
        )
        self.assertIsNone(
            user_allowed_attachment_kinds(self.reviewer, dash, self.company)
        )
        self.assertIsNone(
            user_allowed_attachment_kinds(self.assigner, dash, self.company)
        )
        self.assertEqual(
            user_allowed_attachment_kinds(self.viewer, dash, self.company),
            {"deck"},
        )

    def test_can_manage_viewers_only_when_published(self):
        draft = self._dashboard(status=DashboardStatus.DRAFT)
        published = self._dashboard(status=DashboardStatus.PUBLISHED)
        self.assertFalse(
            can_user_manage_dashboard_viewers(self.assigner, draft, self.company)
        )
        self.assertTrue(
            can_user_manage_dashboard_viewers(self.assigner, published, self.company)
        )

    def test_reviewer_filter_pending_review(self):
        draft = self._dashboard()
        under = self._dashboard(status=DashboardStatus.UNDER_REVIEW)
        published = self._dashboard(status=DashboardStatus.PUBLISHED)

        qs = dashboards_queryset_for_user(self.reviewer, self.company)
        filtered = filter_dashboards_queryset(
            qs, self.reviewer, self.company, FILTER_PENDING_REVIEW
        )
        ids = set(filtered.values_list("pk", flat=True))
        self.assertIn(under.pk, ids)
        self.assertNotIn(draft.pk, ids)
        self.assertNotIn(published.pk, ids)

        filters = available_dashboard_filters(self.reviewer, self.company, qs)
        keys = {item["key"] for item in filters}
        self.assertIn(FILTER_PENDING_REVIEW, keys)

    def test_can_delete_drafts_permission(self):
        deleter = self._user("draft_del", "del@example.com")
        CompanyMembership.objects.create(
            user=deleter,
            company=self.company,
            can_upload=True,
            can_delete_drafts=True,
        )
        draft = self._dashboard(creator=deleter)
        self.assertTrue(can_user_delete_dashboard(deleter, draft, self.company))

    def test_submit_endpoint_requires_login_and_permission(self):
        draft = self._dashboard()
        client = Client()
        client.post("/login/", {"username": "wf_creator", "password": "Test@1234"})
        client.post("/select-company/", {"company_id": self.company.pk})
        response = client.post(f"/dashboards/{draft.pk}/submit/")
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.status, DashboardStatus.UNDER_REVIEW)

    def test_reviewer_cannot_see_rejected_dashboard_of_others(self):
        rejected = self._dashboard(status=DashboardStatus.REJECTED)
        self.assertFalse(user_can_see_dashboard(self.reviewer, rejected, self.company))

    def test_superuser_sees_all_drafts_in_company(self):
        superuser = User.objects.create_superuser(
            "wf_super", "super@example.com", "Test@1234"
        )
        profile = superuser.profile
        profile.two_factor_enabled = False
        profile.save(update_fields=["two_factor_enabled"])
        draft = self._dashboard(status=DashboardStatus.DRAFT)
        ids = set(
            dashboards_queryset_for_user(superuser, self.company).values_list(
                "pk", flat=True
            )
        )
        self.assertIn(draft.pk, ids)
        self.assertTrue(user_can_see_dashboard(superuser, draft, self.company))

    def test_can_review_legacy_draft_when_v2_disabled(self):
        self.company.use_workflow_v2 = False
        self.company.save(update_fields=["use_workflow_v2"])
        draft = self._dashboard()
        self.assertTrue(can_user_review(self.reviewer, draft, self.company))

    def test_return_published_to_review(self):
        dash = self._dashboard(status=DashboardStatus.PUBLISHED)
        dash.submitted_at = dash.created_at
        dash.published_at = dash.created_at
        dash.save(update_fields=["submitted_at", "published_at"])
        DashboardViewer.objects.create(
            dashboard=dash,
            user=self.viewer,
            granted_by=self.assigner,
        )
        self.assertTrue(
            can_user_return_published_to_review(self.reviewer, dash, self.company)
        )
        return_published_dashboard_to_review(self.reviewer, dash, self.company)
        dash.refresh_from_db()
        self.assertEqual(dash.status, DashboardStatus.UNDER_REVIEW)
        self.assertIsNone(dash.published_at)
        self.assertIsNotNone(dash.submitted_at)
        self.assertFalse(DashboardViewer.objects.filter(dashboard=dash).exists())
        self.assertFalse(user_can_see_dashboard(self.viewer, dash, self.company))

        qs = dashboards_queryset_for_user(self.reviewer, self.company)
        filtered = filter_dashboards_queryset(
            qs, self.reviewer, self.company, FILTER_PENDING_REVIEW
        )
        self.assertIn(dash.pk, set(filtered.values_list("pk", flat=True)))

    def test_return_published_to_review_forbidden_for_viewer(self):
        published = self._dashboard(status=DashboardStatus.PUBLISHED)
        self.assertFalse(
            can_user_return_published_to_review(self.viewer, published, self.company)
        )

    def test_return_published_to_review_endpoint(self):
        dash = self._dashboard(status=DashboardStatus.PUBLISHED)
        client = Client()
        client.post("/login/", {"username": "wf_reviewer", "password": "Test@1234"})
        client.post("/select-company/", {"company_id": self.company.pk})
        response = client.post(f"/dashboards/{dash.pk}/return-to-review/")
        self.assertEqual(response.status_code, 302)
        dash.refresh_from_db()
        self.assertEqual(dash.status, DashboardStatus.UNDER_REVIEW)
