"""Workflow notification email tests."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from accounts_app.services.email_branding import BRAND_BLUE
from accounts_app.services.workflow_email import (
    build_auth_link,
    notify_creator_rejected,
    notify_reviewers_pending,
    notify_viewers_assigned,
    notify_viewers_published,
)
from audit_app.models import DashboardStatus
from tests.factories import make_dashboard, make_membership, make_user


@pytest.mark.unit
def test_build_auth_link_points_to_target(monkeypatch):
    monkeypatch.delenv("PUBLIC_SITE_URL", raising=False)
    link = build_auth_link("https://example.com/", "/dashboards/42/")
    assert link == "https://example.com/dashboards/42/"


@pytest.mark.django_db
def test_reviewer_emails_exclude_creator(btc_company):
    creator = make_user("creator", email="creator@example.com")
    reviewer = make_user("reviewer", email="reviewer@example.com")
    make_membership(creator, btc_company, can_upload=True)
    make_membership(reviewer, btc_company, can_review=True)

    dashboard = make_dashboard(btc_company, creator, name="Pending", status=DashboardStatus.DRAFT)
    sent: list[str] = []

    def capture(cfg, *, to_addr, subject, plain, html):
        sent.append(to_addr)

    with patch("accounts_app.services.workflow_email._load_smtp_cfg", return_value={"host": "x", "from": "a@b.c"}):
        with patch("accounts_app.services.workflow_email.send_branded_email_smtp", side_effect=capture):
            notify_reviewers_pending(dashboard, base_url="https://example.com/", submit_kind="new")

    assert sent == ["reviewer@example.com"]
    assert "creator@example.com" not in sent


@pytest.mark.django_db
def test_viewer_emails_exclude_reviewer(btc_company):
    creator = make_user("pub_creator", email="pub_creator@example.com")
    reviewer = make_user("pub_reviewer", email="pub_reviewer@example.com")
    viewer = make_user("pub_viewer", email="pub_viewer@example.com")
    make_membership(creator, btc_company, can_upload=True)
    make_membership(reviewer, btc_company, can_review=True)
    make_membership(viewer, btc_company)

    dashboard = make_dashboard(btc_company, creator, name="Published", status=DashboardStatus.PUBLISHED)
    from audit_app.models import DashboardViewer

    DashboardViewer.objects.create(dashboard=dashboard, user=viewer, granted_by=reviewer)
    sent: list[str] = []

    def capture(cfg, *, to_addr, subject, plain, html):
        sent.append(to_addr)

    with patch("accounts_app.services.workflow_email._load_smtp_cfg", return_value={"host": "x", "from": "a@b.c"}):
        with patch("accounts_app.services.workflow_email.send_branded_email_smtp", side_effect=capture):
            notify_viewers_published(
                dashboard,
                base_url="https://example.com/",
                reviewer=reviewer,
            )

    assert sent == ["pub_viewer@example.com"]
    assert "pub_reviewer@example.com" not in sent


@pytest.mark.django_db
def test_viewer_assigned_email_bilingual(btc_company):
    assigner = make_user("asg_assigner", email="asg_assigner@example.com")
    viewer = make_user("asg_viewer", email="asg_viewer@example.com")
    creator = make_user("asg_creator", email="asg_creator@example.com")
    make_membership(creator, btc_company, can_upload=True)
    make_membership(assigner, btc_company, can_assign_dashboard_viewers=True)
    make_membership(viewer, btc_company)

    dashboard = make_dashboard(btc_company, creator, name="Assigned Dash", status=DashboardStatus.PUBLISHED)
    captured: dict = {}

    def capture(cfg, *, to_addr, subject, plain, html):
        captured["to"] = to_addr
        captured["subject"] = subject
        captured["html"] = html
        captured["plain"] = plain

    with patch("accounts_app.services.workflow_email._load_smtp_cfg", return_value={"host": "x", "from": "a@b.c"}):
        with patch("accounts_app.services.workflow_email.send_branded_email_smtp", side_effect=capture):
            notify_viewers_assigned(
                dashboard,
                user_ids=[viewer.pk],
                base_url="https://example.com/",
                granted_by=assigner,
            )

    assert captured["to"] == "asg_viewer@example.com"
    assert "New Dashboard Available" in captured["subject"]
    assert "لوحة تحكم جديدة متاحة لك" in captured["subject"]
    assert "Assigned Dash" in captured["html"]
    assert "عرض اللوحة" in captured["html"]
    assert "View Dashboard" in captured["html"]
    assert f"/dashboards/{dashboard.pk}/" in captured["html"]
    assert BRAND_BLUE in captured["html"]
    assert "تم نشر لوحة تحكم جديدة" in captured["plain"]


@pytest.mark.django_db
def test_rejection_email_to_creator(btc_company):
    creator = make_user("rej_creator", email="rej_creator@example.com")
    reviewer = make_user("rej_reviewer", email="rej_reviewer@example.com")
    make_membership(creator, btc_company, can_upload=True)
    make_membership(reviewer, btc_company, can_review=True)

    dashboard = make_dashboard(btc_company, creator, name="Rejected", status=DashboardStatus.DRAFT)
    captured: dict = {}

    def capture(cfg, *, to_addr, subject, plain, html):
        captured["to"] = to_addr
        captured["subject"] = subject
        captured["html"] = html

    with patch("accounts_app.services.workflow_email._load_smtp_cfg", return_value={"host": "x", "from": "a@b.c"}):
        with patch("accounts_app.services.workflow_email.send_branded_email_smtp", side_effect=capture):
            notify_creator_rejected(
                dashboard,
                base_url="https://example.com/",
                reason="Missing data",
                reviewer=reviewer,
            )

    assert captured["to"] == "rej_creator@example.com"
    assert "Rejected" in captured["subject"]
    assert "Missing data" in captured["html"]
    assert BRAND_BLUE in captured["html"]
    assert "/dashboards/" in captured["html"]
    assert "/login/?next=" not in captured["html"]


@pytest.mark.django_db
def test_superuser_reviewer_receives_pending_email_when_opted_in(btc_company):
    creator = make_user("su_creator", email="su_creator@example.com")
    reviewer = make_user("su_reviewer", email="su_reviewer@example.com", password="Test@1234")
    reviewer.is_superuser = True
    reviewer.save(update_fields=["is_superuser"])
    reviewer.profile.receive_workflow_emails = True
    reviewer.profile.save(update_fields=["receive_workflow_emails"])
    make_membership(creator, btc_company, can_upload=True)

    dashboard = make_dashboard(btc_company, creator, name="Super Pending", status=DashboardStatus.DRAFT)
    sent: list[str] = []

    def capture(cfg, *, to_addr, subject, plain, html):
        sent.append(to_addr)

    with patch("accounts_app.services.workflow_email._load_smtp_cfg", return_value={"host": "x", "from": "a@b.c"}):
        with patch("accounts_app.services.workflow_email.send_branded_email_smtp", side_effect=capture):
            notify_reviewers_pending(dashboard, base_url="https://example.com/", submit_kind="new")

    assert sent == ["su_reviewer@example.com"]


@pytest.mark.django_db
def test_superuser_without_opt_in_does_not_receive_pending_email(btc_company):
    creator = make_user("su2_creator", email="su2_creator@example.com")
    reviewer = make_user("su2_reviewer", email="su2_reviewer@example.com")
    reviewer.is_superuser = True
    reviewer.save(update_fields=["is_superuser"])
    reviewer.profile.receive_workflow_emails = False
    reviewer.profile.save(update_fields=["receive_workflow_emails"])
    make_membership(creator, btc_company, can_upload=True)

    dashboard = make_dashboard(btc_company, creator, name="No Super Mail", status=DashboardStatus.DRAFT)
    sent: list[str] = []

    def capture(cfg, *, to_addr, subject, plain, html):
        sent.append(to_addr)

    with patch("accounts_app.services.workflow_email._load_smtp_cfg", return_value={"host": "x", "from": "a@b.c"}):
        with patch("accounts_app.services.workflow_email.send_branded_email_smtp", side_effect=capture):
            notify_reviewers_pending(dashboard, base_url="https://example.com/", submit_kind="new")

    assert sent == []


@pytest.mark.django_db
def test_reviewer_without_workflow_emails_opt_out_does_not_receive(btc_company):
    creator = make_user("opt_creator", email="opt_creator@example.com")
    reviewer = make_user("opt_reviewer", email="opt_reviewer@example.com")
    reviewer.profile.receive_workflow_emails = False
    reviewer.profile.save(update_fields=["receive_workflow_emails"])
    make_membership(creator, btc_company, can_upload=True)
    make_membership(reviewer, btc_company, can_review=True)

    dashboard = make_dashboard(btc_company, creator, name="Opt Out", status=DashboardStatus.DRAFT)
    sent: list[str] = []

    def capture(cfg, *, to_addr, subject, plain, html):
        sent.append(to_addr)

    with patch("accounts_app.services.workflow_email._load_smtp_cfg", return_value={"host": "x", "from": "a@b.c"}):
        with patch("accounts_app.services.workflow_email.send_branded_email_smtp", side_effect=capture):
            notify_reviewers_pending(dashboard, base_url="https://example.com/", submit_kind="new")

    assert sent == []


@pytest.mark.django_db
def test_pending_email_bilingual_cta(btc_company):
    creator = make_user("pend_creator", email="pend_creator@example.com")
    reviewer = make_user("pend_reviewer", email="pend_reviewer@example.com")
    make_membership(creator, btc_company, can_upload=True)
    make_membership(reviewer, btc_company, can_review=True)

    dashboard = make_dashboard(btc_company, creator, name="Wait", status=DashboardStatus.DRAFT)
    captured: dict = {}

    def capture(cfg, *, to_addr, subject, plain, html):
        captured["html"] = html

    with patch("accounts_app.services.workflow_email._load_smtp_cfg", return_value={"host": "x", "from": "a@b.c"}):
        with patch("accounts_app.services.workflow_email.send_branded_email_smtp", side_effect=capture):
            notify_reviewers_pending(dashboard, base_url="https://example.com/", submit_kind="resubmit")

    html = captured["html"]
    assert "مراجعة اللوحة" in html
    assert "Review Dashboard" in html
    assert 'dir="rtl"' in html
    assert 'dir="ltr"' in html
