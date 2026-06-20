"""Email deliverability helpers (headers, subjects, escaping)."""
from __future__ import annotations

from email.mime.text import MIMEText
from unittest.mock import patch

import pytest

from accounts_app.services.email_branding import (
    BRAND_SUBJECT_PREFIX,
    enrich_message_headers,
    format_bilingual_subject,
    render_otp_code,
    send_branded_email_smtp,
    truncate_email_subject,
)
from accounts_app.services.workflow_email import build_auth_link


@pytest.mark.unit
def test_format_bilingual_subject_includes_brand_prefix():
    subject = format_bilingual_subject(
        text_ar="طلب مراجعة لوحة تحكم",
        text_en="Dashboard Pending Review",
    )
    assert subject.startswith(BRAND_SUBJECT_PREFIX)
    assert "طلب مراجعة لوحة تحكم" in subject
    assert "Dashboard Pending Review" in subject


@pytest.mark.unit
def test_truncate_email_subject_long_text():
    long_text = "أ" * 100
    subject = truncate_email_subject(long_text, max_length=78)
    assert len(subject) <= 78
    assert subject.endswith("…")


@pytest.mark.unit
def test_enrich_message_headers_adds_required_fields():
    msg = MIMEText("hello", "plain", "utf-8")
    cfg = {"reply_to": "support@example.com"}
    enrich_message_headers(
        msg,
        cfg,
        from_addr="noreply@alissa-ia.com",
        to_addr="user@example.com",
    )
    assert msg["Message-ID"]
    assert msg["Date"]
    assert msg["MIME-Version"] == "1.0"
    assert msg["Reply-To"] == "support@example.com"
    assert msg["X-Auto-Response-Suppress"] == "All"
    assert msg["To"] == "user@example.com"


@pytest.mark.unit
def test_send_branded_email_smtp_sets_headers(monkeypatch):
    captured: dict = {}

    def fake_send(cfg, *, from_addr, to_addr, msg):
        captured["msg"] = msg

    monkeypatch.setattr(
        "accounts_app.services.email_branding._smtp_send_message",
        fake_send,
    )

    send_branded_email_smtp(
        {"host": "mail.example.com", "from": "noreply@alissa-ia.com"},
        to_addr="user@example.com",
        subject="Test",
        plain="plain body",
        html="<p>html</p>",
    )

    msg = captured["msg"]
    assert msg["Message-ID"]
    assert msg["Reply-To"] == "noreply@alissa-ia.com"


@pytest.mark.unit
def test_otp_code_html_is_escaped():
    html = render_otp_code("<123>")
    assert "&lt;123&gt;" in html
    assert "<123>" not in html


@pytest.mark.unit
def test_build_auth_link_prefers_public_site_url(monkeypatch):
    monkeypatch.setenv("PUBLIC_SITE_URL", "https://dash-audit.alissa-ia.com")
    link = build_auth_link("http://internal.local/", "/dashboards/5/")
    assert link == "https://dash-audit.alissa-ia.com/dashboards/5/"


@pytest.mark.unit
def test_observation_subject_is_branded_not_full_body():
    from ai_excel_dashboard import send_audit_observation_email_smtp

    long_obs = "ملاحظة " * 200
    captured: dict = {}

    def fake_plain(cfg, *, to_addr, subject, plain):
        captured["subject"] = subject
        captured["plain"] = plain

    with patch(
        "accounts_app.services.email_branding.send_plain_email_smtp",
        side_effect=fake_plain,
    ):
        send_audit_observation_email_smtp(
            {"host": "x", "from": "noreply@alissa-ia.com"},
            to_addr="user@example.com",
            observation=long_obs,
        )

    assert captured["subject"].startswith(BRAND_SUBJECT_PREFIX)
    assert long_obs not in captured["subject"]
    assert long_obs.strip() in captured["plain"]
