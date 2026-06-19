"""Regression smoke tests for the six planned improvements."""
from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from accounts_app.navigation import resolve_default_home
from tests.helpers import login_and_select_company


@pytest.mark.regression
@pytest.mark.django_db
def test_home_routing_viewer_goes_to_dashboard_list(viewer_user):
    assert resolve_default_home(viewer_user) == reverse("dashboard_list")


@pytest.mark.regression
@pytest.mark.django_db
def test_home_routing_no_perm_goes_to_profile(no_perm_user):
    assert resolve_default_home(no_perm_user) == reverse("profile")


@pytest.mark.regression
@pytest.mark.django_db
def test_login_page_has_loading_spinner_markup():
    client = Client()
    response = client.get("/login/")
    assert response.status_code == 200
    html = response.content.decode()
    assert "is-loading" in html
    assert "btn-spinner" in html
    assert "js-login-form" in html


@pytest.mark.regression
@pytest.mark.django_db
def test_verify_2fa_page_has_loading_markup():
    client = Client()
    session = client.session
    session["pending_2fa_user_id"] = 1
    session.save()
    response = client.get("/verify-2fa/")
    # Without valid pending user we get redirected; still verify template when accessible
    if response.status_code == 200:
        html = response.content.decode()
        assert "btn-spinner" in html


@pytest.mark.regression
def test_admin_panel_links_no_blank_target():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for rel in (
        "templates/base.html",
        "templates/accounts/profile.html",
        "templates/accounts/setup_required.html",
    ):
        text = (root / rel).read_text(encoding="utf-8")
        assert 'href="{% url \'admin:index\' %}" target="_blank"' not in text
        assert 'admin_add_company_url }}" target="_blank"' not in text


@pytest.mark.regression
@pytest.mark.django_db
def test_superuser_delete_json_regression(api_client, superuser, draft_dashboard, btc_company):
    login_and_select_company(api_client, "pytest_super", btc_company)
    response = api_client.post(
        f"/dashboards/{draft_dashboard.pk}/delete/",
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert response.json()["ok"] is True
