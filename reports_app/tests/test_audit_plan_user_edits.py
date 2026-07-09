"""Tests for audit plan user edits persistence and reviewer attachment management."""
from __future__ import annotations

import json

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from audit_app.models import Company, CompanyMembership, Dashboard, DashboardStatus, UploadSession
from reports_app.dashboard_workflow import (
    can_user_manage_review_attachments,
    can_user_save_dashboard_user_edits,
)
from reports_app.services.report_generation import (
    inject_dashboard_serve_context,
    inject_user_edits_persist_script,
    validate_dashboard_user_edits_payload,
)


class AuditPlanUserEditsTests(TestCase):
    def setUp(self):
        self.company, _ = Company.objects.get_or_create(
            code="BTC",
            defaults={"name": "BTC", "excel_company_names": ["BTC"], "use_workflow_v2": True},
        )
        self.company.ensure_attachment_settings()
        self.reviewer = User.objects.create_user(username="plan_reviewer", password="pass12345!")
        CompanyMembership.objects.create(
            company=self.company,
            user=self.reviewer,
            can_review=True,
        )
        session = UploadSession.objects.create(
            source_name="test.xlsx",
            mode="IAD",
            locale="en",
            raw_data_json='{"columns":["a"],"data":[["1"]]}',
        )
        self.dashboard = Dashboard.objects.create(
            name="Plan Draft",
            report_id="plan-draft-001",
            company=self.company,
            created_by=self.reviewer,
            upload_session=session,
            status=DashboardStatus.DRAFT,
        )

    def test_validate_dashboard_user_edits_payload_normalizes_rows(self):
        payload = validate_dashboard_user_edits_payload(
            {
                "v": 1,
                "planRows": [[" Alpha ", "Beta", "", "", "", "", ""]],
                "planCellBg": [["#ff0000", "bad", "", "", "", "", ""]],
                "reviewsNote": "note",
            }
        )
        self.assertEqual(payload["planRows"][0][0], "Alpha")
        self.assertEqual(payload["planCellBg"][0][0], "#ff0000")
        self.assertEqual(payload["planCellBg"][0][1], "#ffffff")
        self.assertEqual(payload["reviewsNote"], "note")

    def test_inject_user_edits_persist_script_inserts_json_block(self):
        html = "<html><body><div>ok</div></body></html>"
        out = inject_user_edits_persist_script(html, '{"v":1,"planRows":[]}')
        self.assertIn('id="audit-dashboard-user-persist"', out)
        self.assertIn('"planRows":[]', out)

    def test_inject_dashboard_serve_context_sets_save_flags(self):
        html = (
            "<html><head>"
            "window.__AI_EXCEL_USER_EDITS_SAVE_URL__=null;"
            "window.__AI_EXCEL_CAN_SAVE_USER_EDITS__=false;"
            "</head><body></body></html>"
        )
        out = inject_dashboard_serve_context(
            html,
            mail_url="http://test/api/mail",
            plan_url="http://test/api/plan",
            user_edits_save_url="http://test/save",
            can_save_user_edits=True,
            user_edits_json='{"v":1,"planRows":[["P","A","","","","",""]]}',
        )
        self.assertIn("http://test/save", out)
        self.assertIn("__AI_EXCEL_CAN_SAVE_USER_EDITS__=true", out)
        self.assertIn('"planRows":[["P","A","","","","",""]]', out)

    def test_can_user_save_dashboard_user_edits_until_publish(self):
        self.assertTrue(
            can_user_save_dashboard_user_edits(self.reviewer, self.dashboard, self.company)
        )
        self.dashboard.status = DashboardStatus.PUBLISHED
        self.dashboard.save(update_fields=["status"])
        self.assertFalse(
            can_user_save_dashboard_user_edits(self.reviewer, self.dashboard, self.company)
        )

    def test_dashboard_user_edits_api_persists(self):
        client = Client()
        client.force_login(self.reviewer)
        session = client.session
        session["active_company_id"] = self.company.pk
        session.save()

        url = reverse("dashboard_user_edits", args=[self.dashboard.pk])
        body = {
            "v": 1,
            "planRows": [["Project X", "Finance", "Bob", "Open", "10%", "20%", "30%"]],
            "planCellBg": [],
            "reviewsNote": "saved",
        }
        resp = client.post(
            url,
            data=json.dumps(body),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.dashboard.refresh_from_db()
        stored = json.loads(self.dashboard.user_edits_json)
        self.assertEqual(stored["planRows"][0][0], "Project X")
        self.assertEqual(stored["reviewsNote"], "saved")

    def test_can_user_manage_review_attachments_only_under_review(self):
        self.dashboard.status = DashboardStatus.UNDER_REVIEW
        self.dashboard.save(update_fields=["status"])
        self.assertTrue(
            can_user_manage_review_attachments(self.reviewer, self.dashboard, self.company)
        )
        self.dashboard.status = DashboardStatus.PUBLISHED
        self.dashboard.save(update_fields=["status"])
        self.assertFalse(
            can_user_manage_review_attachments(self.reviewer, self.dashboard, self.company)
        )


class ResubmitKeepExcelTests(TestCase):
    def setUp(self):
        self.company, _ = Company.objects.get_or_create(
            code="BTC",
            defaults={"name": "BTC", "excel_company_names": ["BTC"], "use_workflow_v2": True},
        )
        self.company.ensure_attachment_settings()
        self.creator = User.objects.create_user(username="keep_excel_user", password="pass12345!")
        CompanyMembership.objects.create(
            company=self.company,
            user=self.creator,
            can_upload=True,
        )
        session = UploadSession.objects.create(
            source_name="orig.xlsx",
            mode="IAD",
            locale="en",
            raw_data_json='{"columns":["a"],"data":[["1"]],"source_name":"orig.xlsx"}',
        )
        self.dashboard = Dashboard.objects.create(
            name="Keep Excel",
            report_id="keep-excel-001",
            company=self.company,
            created_by=self.creator,
            upload_session=session,
            source_files={"excel": ["orig.xlsx"]},
            status=DashboardStatus.DRAFT,
            template_type="IAD",
        )

    def _post_resubmit_without_file(self, extra=None):
        client = Client()
        client.force_login(self.creator)
        session = client.session
        session["active_company_id"] = self.company.pk
        session.save()
        data = {
            "dashboard_name": "Keep Excel Renamed",
            "icon": "bi-bar-chart-line-fill",
            "template_type": "IAD",
            "resubmit_dashboard_id": str(self.dashboard.pk),
        }
        if extra:
            data.update(extra)
        return client.post(reverse("analyze"), data=data)

    def test_resubmit_without_new_excel_keeps_existing_data(self):
        resp = self._post_resubmit_without_file()
        self.assertEqual(resp.status_code, 302)
        self.dashboard.refresh_from_db()
        self.assertEqual(self.dashboard.name, "Keep Excel Renamed")
        self.assertIsNotNone(self.dashboard.upload_session)
        self.assertIn("orig.xlsx", self.dashboard.source_files.get("excel", []))

    def test_resubmit_with_excel_removed_requires_new_file(self):
        resp = self._post_resubmit_without_file({"remove_excel": "1"})
        self.assertEqual(resp.status_code, 200)
        self.dashboard.refresh_from_db()
        self.assertEqual(self.dashboard.name, "Keep Excel")
