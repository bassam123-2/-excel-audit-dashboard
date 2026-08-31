from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from accounts_app.services import two_factor
from audit_app.models import Company, CompanyAttachmentSetting, CompanyMembership, Dashboard, DashboardStatus, DashboardViewer
from reports_app.dashboard_workflow import dashboards_queryset_for_user, has_upload_perm


class CompanyAccessTests(TestCase):
    def setUp(self):
        self.btc, _ = Company.objects.get_or_create(
            code="BTC",
            defaults={"name": "BTC", "excel_company_names": ["BTC"]},
        )
        self.nat, _ = Company.objects.get_or_create(
            code="NAT",
            defaults={"name": "NAT", "excel_company_names": ["NAT"]},
        )
        self.btc.ensure_attachment_settings()
        self.nat.ensure_attachment_settings()

        self.btc_uploader = User.objects.create_user(
            "btc_uploader", password="Test@1234", email="btc@example.com"
        )
        profile = self.btc_uploader.profile
        profile.two_factor_enabled = False
        profile.save(update_fields=["two_factor_enabled"])
        CompanyMembership.objects.create(
            user=self.btc_uploader,
            company=self.btc,
            can_upload=True,
        )

        self.nat_viewer = User.objects.create_user(
            "nat_viewer", password="Test@1234", email="nat@example.com"
        )
        profile = self.nat_viewer.profile
        profile.two_factor_enabled = False
        profile.save(update_fields=["two_factor_enabled"])
        CompanyMembership.objects.create(
            user=self.nat_viewer,
            company=self.nat,
        )

    def _dashboard(self, company, creator, name="Dash"):
        return Dashboard.objects.create(
            name=name,
            report_id=f"rid-{name}-{company.code}",
            company=company,
            created_by=creator,
            status=DashboardStatus.PUBLISHED,
        )

    def test_dashboard_isolation_between_companies(self):
        self._dashboard(self.btc, self.btc_uploader, "BTC Dash")
        self._dashboard(self.nat, self.nat_viewer, "NAT Dash")

        btc_ids = set(
            dashboards_queryset_for_user(self.btc_uploader, self.btc).values_list(
                "pk", flat=True
            )
        )
        nat_ids = set(
            dashboards_queryset_for_user(self.nat_viewer, self.nat).values_list(
                "pk", flat=True
            )
        )

        self.assertEqual(len(btc_ids), 1)
        self.assertEqual(len(nat_ids), 1)
        self.assertTrue(btc_ids.isdisjoint(nat_ids))

    def test_company_upload_permission(self):
        self.assertTrue(has_upload_perm(self.btc_uploader, self.btc))
        self.assertFalse(has_upload_perm(self.btc_uploader, self.nat))
        self.assertFalse(has_upload_perm(self.nat_viewer, self.nat))

    def test_view_own_only_sees_only_creator_dashboards(self):
        owner = User.objects.create_user(
            "btc_owner", password="Test@1234", email="owner@example.com"
        )
        owner.profile.two_factor_enabled = False
        owner.profile.save(update_fields=["two_factor_enabled"])
        CompanyMembership.objects.create(
            user=owner,
            company=self.btc,
            can_upload=True,
            can_view_own_only=True,
        )

        other = User.objects.create_user(
            "btc_other", password="Test@1234", email="other@example.com"
        )
        other.profile.two_factor_enabled = False
        other.profile.save(update_fields=["two_factor_enabled"])
        CompanyMembership.objects.create(
            user=other,
            company=self.btc,
            can_upload=True,
            can_view_own_only=True,
        )

        own_dash = self._dashboard(self.btc, owner, "Owner Dash")
        other_dash = self._dashboard(self.btc, other, "Other Dash")

        owner_ids = set(
            dashboards_queryset_for_user(owner, self.btc).values_list("pk", flat=True)
        )
        self.assertEqual(owner_ids, {own_dash.pk})
        self.assertNotIn(other_dash.pk, owner_ids)

    def test_assigned_viewer_sees_published_dashboards(self):
        viewer = User.objects.create_user(
            "btc_viewer", password="Test@1234", email="viewer@example.com"
        )
        viewer.profile.two_factor_enabled = False
        viewer.profile.save(update_fields=["two_factor_enabled"])
        CompanyMembership.objects.create(
            user=viewer,
            company=self.btc,
        )

        creator = User.objects.create_user(
            "btc_creator", password="Test@1234", email="creator@example.com"
        )
        creator.profile.two_factor_enabled = False
        creator.profile.save(update_fields=["two_factor_enabled"])

        dash_a = self._dashboard(self.btc, creator, "Published A")
        dash_b = self._dashboard(self.btc, self.btc_uploader, "Published B")
        DashboardViewer.objects.create(dashboard=dash_a, user=viewer, granted_by=creator)
        DashboardViewer.objects.create(dashboard=dash_b, user=viewer, granted_by=creator)

        viewer_ids = set(
            dashboards_queryset_for_user(viewer, self.btc).values_list("pk", flat=True)
        )
        self.assertEqual(viewer_ids, {dash_a.pk, dash_b.pk})

    def test_delete_draft_superuser_only(self):
        from reports_app.dashboard_workflow import can_user_delete_dashboard

        deleter = User.objects.create_user(
            "draft_deleter", password="Test@1234", email="del@example.com"
        )
        deleter.profile.two_factor_enabled = False
        deleter.profile.save(update_fields=["two_factor_enabled"])
        CompanyMembership.objects.create(
            user=deleter,
            company=self.btc,
            can_delete_drafts=True,
        )
        superuser = User.objects.create_superuser(
            "su_deleter", "su@example.com", "Test@1234"
        )

        draft = Dashboard.objects.create(
            name="Draft Dash",
            report_id="rid-draft-btc",
            company=self.btc,
            created_by=deleter,
            status=DashboardStatus.DRAFT,
        )
        published = self._dashboard(self.btc, deleter, "Published Dash")

        self.assertTrue(can_user_delete_dashboard(deleter, draft, self.btc))
        self.assertFalse(can_user_delete_dashboard(deleter, published, self.btc))
        self.assertTrue(can_user_delete_dashboard(superuser, draft, self.btc))
        self.assertTrue(can_user_delete_dashboard(superuser, published, self.btc))

    def test_published_dashboard_not_deletable_by_non_superuser(self):
        owner = User.objects.create_user(
            "pub_owner", password="Test@1234", email="pub@example.com"
        )
        owner.profile.two_factor_enabled = False
        owner.profile.save(update_fields=["two_factor_enabled"])
        CompanyMembership.objects.create(
            user=owner,
            company=self.btc,
            can_delete_drafts=True,
        )
        dash = self._dashboard(self.btc, owner, "Published")

        client = Client()
        client.force_login(owner)
        client.post("/select-company/", {"company_id": self.btc.pk})
        response = client.post(f"/dashboards/{dash.pk}/delete/")
        self.assertEqual(response.status_code, 302)
        dash.refresh_from_db()
        self.assertFalse(dash.is_deleted)

    def test_disabled_attachment_not_in_form_slots(self):
        CompanyAttachmentSetting.objects.filter(
            company=self.btc, attachment_kind="tgaViolations"
        ).update(is_enabled=False)

        from reports_app.services.report_generation import build_attachment_form_slots

        slots = build_attachment_form_slots(None, locale="en", company=self.btc)
        kinds = {slot["kind"] for slot in slots}
        self.assertNotIn("tgaViolations", kinds)
        self.assertIn("deck", kinds)

    def test_disabled_attachment_toggles_omitted_from_dashboard_html(self):
        from ai_excel_dashboard import build_deck_attach_toggle_html

        CompanyAttachmentSetting.objects.filter(
            company=self.btc, attachment_kind="tgaViolations"
        ).update(is_enabled=False)
        CompanyAttachmentSetting.objects.filter(
            company=self.btc, attachment_kind="missingVehicle"
        ).update(is_enabled=False)

        enabled = {
            kind
            for kind in ("deck", "highRisk", "tgaViolations", "missingVehicle")
            if CompanyAttachmentSetting.objects.filter(
                company=self.btc, attachment_kind=kind, is_enabled=True
            ).exists()
        }
        html = build_deck_attach_toggle_html("en", enabled)
        self.assertIn("audit-deck-attach-cb", html)
        self.assertNotIn("audit-tga-violations-cb", html)
        self.assertNotIn("audit-missing-vehicle-cb", html)

    def test_password_expiry_redirect(self):
        profile = self.btc_uploader.profile
        profile.password_expiry_enabled = True
        profile.password_changed_at = timezone.now() - timedelta(days=200)
        profile.save(update_fields=["password_expiry_enabled", "password_changed_at"])

        from accounts_app.middleware import PasswordExpiryMiddleware
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get("/dashboards/")
        request.user = self.btc_uploader
        middleware = PasswordExpiryMiddleware(lambda req: req)
        response = middleware(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/profile/", response.url)
        self.assertIn("force_password=1", response.url)

    def test_password_expiry_skipped_when_disabled(self):
        profile = self.btc_uploader.profile
        profile.password_expiry_enabled = False
        profile.password_changed_at = timezone.now() - timedelta(days=200)
        profile.save(update_fields=["password_expiry_enabled", "password_changed_at"])

        from accounts_app.middleware import PasswordExpiryMiddleware
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get("/dashboards/")
        request.user = self.btc_uploader
        from django.http import HttpResponseRedirect

        middleware = PasswordExpiryMiddleware(lambda req: req)
        response = middleware(request)
        self.assertNotIsInstance(response, HttpResponseRedirect)

    def test_two_factor_otp_roundtrip(self):
        code = two_factor.generate_and_store_otp(self.btc_uploader.pk)
        self.assertTrue(two_factor.verify_otp(self.btc_uploader.pk, code))
        self.assertFalse(two_factor.verify_otp(self.btc_uploader.pk, code))

    def test_login_without_2fa(self):
        client = Client()
        client.post(
            "/login/",
            {"username": "btc_uploader", "password": "Test@1234"},
        )
        self.assertIn("_auth_user_id", client.session)
        self.assertIsNone(client.session.get("pending_2fa_user_id"))

    def test_superuser_sidebar_perms_without_active_company(self):
        from django.contrib.auth.models import User
        from django.test import RequestFactory

        from reports_app.context_processors import ui_context

        admin = User.objects.create_superuser(
            "su_test", password="Test@1234", email="su@example.com"
        )
        factory = RequestFactory()
        request = factory.get("/")
        request.user = admin
        request.session = {}
        ctx = ui_context(request)
        # Superuser with multiple seeded companies must pick one before upload/view.
        self.assertFalse(ctx["can_upload_files"])
        self.assertFalse(ctx["can_view_dashboards"])
        self.assertFalse(ctx["can_review_dashboards"])
        self.assertTrue(ctx["needs_company_selection"])

    def test_no_companies_blocks_app_and_redirects(self):
        from django.contrib.auth.models import User
        from django.test import RequestFactory

        from reports_app.context_processors import ui_context

        Company.objects.all().delete()
        admin = User.objects.create_superuser(
            "no_co_admin", password="Test@1234", email="noco@example.com"
        )
        factory = RequestFactory()
        request = factory.get("/")
        request.user = admin
        request.session = {}
        ctx = ui_context(request)
        self.assertTrue(ctx["no_companies_configured"])
        self.assertFalse(ctx["can_upload_files"])
        self.assertFalse(ctx["can_view_dashboards"])
        self.assertTrue(ctx["can_manage_companies"])

        client = Client()
        client.force_login(admin)
        response = client.get("/")
        self.assertRedirects(response, "/setup-required/")

    def test_company_admin_form_shows_all_attachment_toggles(self):
        from audit_app.admin_forms import CompanyAdminForm
        from audit_app.models import ATTACHMENT_KIND_CODES

        form = CompanyAdminForm()
        for code in ATTACHMENT_KIND_CODES:
            self.assertIn(f"att_{code}", form.fields)

    def test_company_admin_form_persists_disabled_attachments(self):
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        from audit_app.admin_forms import (
            ATTACHMENT_KIND_CODES,
            CompanyAdminForm,
            company_attachment_field_name,
        )

        company = Company.objects.create(code="TST", name="Test Co")
        data = {
            "code": "TST",
            "name": "Test Co",
            "company_kind": "main",
            "is_active": "on",
            "excel_company_names": "[]",
        }
        for code in ATTACHMENT_KIND_CODES:
            field_name = company_attachment_field_name(code)
            data[f"{field_name}_1"] = "4"
            if code == "deck":
                continue
            data[f"{field_name}_0"] = "on"

        buffer = BytesIO()
        Image.new("RGB", (8, 8), color="blue").save(buffer, format="PNG")
        logo = SimpleUploadedFile("logo.png", buffer.getvalue(), content_type="image/png")
        form = CompanyAdminForm(data=data, files={"logo": logo}, instance=company)
        self.assertTrue(form.is_valid(), form.errors)
        form.save(commit=False)
        form.save_attachment_settings(company)

        deck = CompanyAttachmentSetting.objects.get(
            company=company, attachment_kind="deck"
        )
        high_risk = CompanyAttachmentSetting.objects.get(
            company=company, attachment_kind="highRisk"
        )
        self.assertFalse(deck.is_enabled)
        self.assertTrue(high_risk.is_enabled)
        self.assertEqual(high_risk.max_files, 4)

    def test_multi_company_user_redirected_to_select_company(self):
        multi = User.objects.create_user(
            "multi_user", password="Test@1234", email="multi@example.com"
        )
        profile = multi.profile
        profile.two_factor_enabled = False
        profile.save(update_fields=["two_factor_enabled"])
        CompanyMembership.objects.create(
            user=multi,
            company=self.btc,
            can_upload=True,
        )
        CompanyMembership.objects.create(
            user=multi,
            company=self.nat,
            can_upload=True,
        )

        client = Client()
        client.post("/login/", {"username": "multi_user", "password": "Test@1234"})
        response = client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/select-company/", response.url)

    def test_multi_company_staff_can_open_admin_without_selecting_company(self):
        multi = User.objects.create_user(
            "multi_staff",
            password="Test@1234",
            email="multi-staff@example.com",
            is_staff=True,
        )
        profile = multi.profile
        profile.two_factor_enabled = False
        profile.save(update_fields=["two_factor_enabled"])
        CompanyMembership.objects.create(
            user=multi,
            company=self.btc,
            can_upload=True,
        )
        CompanyMembership.objects.create(
            user=multi,
            company=self.nat,
            can_upload=True,
        )

        client = Client()
        client.post("/login/", {"username": "multi_staff", "password": "Test@1234"})
        response = client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("/select-company/", response.get("Location", ""))

    def test_login_redirects_to_dashboard_list(self):
        client = Client()
        response = client.post(
            "/login/",
            {"username": "btc_uploader", "password": "Test@1234"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/?template=IAD")

    def test_uploader_can_open_upload_page(self):
        client = Client()
        client.post("/login/", {"username": "btc_uploader", "password": "Test@1234"})
        response = client.get("/upload/")
        self.assertEqual(response.status_code, 200)

    def _multi_company_user(self):
        multi = User.objects.create_user(
            "multi_ctx", password="Test@1234", email="multi@example.com"
        )
        profile = multi.profile
        profile.two_factor_enabled = False
        profile.save(update_fields=["two_factor_enabled"])
        CompanyMembership.objects.create(
            user=multi,
            company=self.btc,
            can_upload=True,
        )
        CompanyMembership.objects.create(
            user=multi,
            company=self.nat,
            can_upload=True,
        )
        return multi

    def test_switch_company_redirects_off_foreign_dashboard(self):
        multi = self._multi_company_user()
        btc_dash = self._dashboard(self.btc, multi, "BTC Only")
        detail_url = f"/dashboards/{btc_dash.pk}/"

        client = Client()
        client.post("/login/", {"username": "multi_ctx", "password": "Test@1234"})
        client.post("/select-company/", {"company_id": self.btc.pk})
        self.assertEqual(client.get(detail_url).status_code, 200)

        response = client.post(
            "/switch-company/",
            {"company_id": self.nat.pk, "next": detail_url},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(response.url.rstrip("/"), ("/", ""))
        self.assertNotIn(f"/dashboards/{btc_dash.pk}/", response.url)

    def test_dashboard_detail_auto_switches_active_company(self):
        from audit_app.company_access import SESSION_ACTIVE_COMPANY_KEY

        multi = self._multi_company_user()
        btc_dash = self._dashboard(self.btc, multi, "BTC Only")

        client = Client()
        client.post("/login/", {"username": "multi_ctx", "password": "Test@1234"})
        client.post("/select-company/", {"company_id": self.nat.pk})
        self.assertEqual(client.session.get(SESSION_ACTIVE_COMPANY_KEY), self.nat.pk)

        response = client.get(f"/dashboards/{btc_dash.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.session.get(SESSION_ACTIVE_COMPANY_KEY), self.btc.pk)

    def test_inactive_company_dashboards_hidden(self):
        dash = self._dashboard(self.btc, self.btc_uploader, "Inactive Dash")
        self.btc.is_active = False
        self.btc.save(update_fields=["is_active"])

        ids = set(
            dashboards_queryset_for_user(self.btc_uploader, self.btc).values_list(
                "pk", flat=True
            )
        )
        self.assertNotIn(dash.pk, ids)

    def test_excel_subcompany_validation_rejects_unknown_code(self):
        import pandas as pd

        from audit_app.company_access import validate_excel_subcompanies_for_tenant

        df = pd.DataFrame(
            {
                "Company": ["BTC"],
                "Subcompany": ["UNKNOWN_SUB"],
            }
        )
        from audit_app.company_access import extract_excel_subcompany_names_from_df

        names = extract_excel_subcompany_names_from_df(df)
        with self.assertRaises(ValueError):
            validate_excel_subcompanies_for_tenant(self.btc, names, locale="en")

    def test_excel_subcompany_validation_accepts_main_company_name(self):
        import pandas as pd

        from audit_app.company_access import (
            extract_excel_subcompany_names_from_df,
            validate_excel_subcompanies_for_tenant,
        )

        df = pd.DataFrame(
            {
                "Company": ["BTC"],
                "Subcompany": ["BTC"],
            }
        )
        names = extract_excel_subcompany_names_from_df(df)
        validate_excel_subcompanies_for_tenant(self.btc, names, locale="en")

    def test_subsidiary_not_selectable_as_active_company(self):
        from audit_app.company_access import set_active_company, user_companies

        sub = Company.objects.create(
            code="BTC-SUB",
            name="BTC Sub",
            company_kind="subsidiary",
            parent=self.btc,
            excel_company_names=["BTC-SUB"],
        )
        CompanyMembership.objects.create(
            user=self.btc_uploader,
            company=sub,
            can_upload=True,
        )
        self.assertNotIn(sub.pk, list(user_companies(self.btc_uploader).values_list("pk", flat=True)))

        client = Client()
        client.force_login(self.btc_uploader)
        request = client.request().wsgi_request
        request.user = self.btc_uploader
        from django.contrib.sessions.middleware import SessionMiddleware

        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session.save()
        self.assertFalse(set_active_company(request, sub.pk))
