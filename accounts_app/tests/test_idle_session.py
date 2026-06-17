from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts_app.middleware import IdleSessionMiddleware
from audit_app.models import Company, CompanyMembership

User = get_user_model()


@override_settings(IDLE_SESSION_TIMEOUT_SECONDS=60)
class IdleSessionMiddlewareTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="idle_user",
            password="Test@1234",
            email="idle@example.com",
        )
        profile = self.user.profile
        profile.two_factor_enabled = False
        profile.save(update_fields=["two_factor_enabled"])
        company, _ = Company.objects.get_or_create(
            code="IDL",
            defaults={"name": "Idle Co", "excel_company_names": ["IDL"]},
        )
        company.ensure_attachment_settings()
        CompanyMembership.objects.create(
            user=self.user,
            company=company,
            can_upload=True,
            can_view=True,
        )

    def test_recent_activity_keeps_session(self):
        self.client.login(username="idle_user", password="Test@1234")
        session = self.client.session
        session[IdleSessionMiddleware.SESSION_LAST_ACTIVITY_KEY] = timezone.now().timestamp()
        session.save()
        response = self.client.get("/")
        self.assertNotEqual(response.status_code, 302)
        self.assertNotIn("session_expired=1", response.get("Location", ""))

    def test_idle_timeout_logs_out(self):
        self.client.login(username="idle_user", password="Test@1234")
        session = self.client.session
        session[IdleSessionMiddleware.SESSION_LAST_ACTIVITY_KEY] = (
            timezone.now() - timedelta(seconds=120)
        ).timestamp()
        session.save()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("session_expired=1", response.url)

    def test_login_page_shows_session_expired_message(self):
        response = self.client.get(reverse("login") + "?session_expired=1")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "inactivity")
