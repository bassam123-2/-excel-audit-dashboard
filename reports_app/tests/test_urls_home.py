"""Home URL routing tests."""
from __future__ import annotations

import pytest
from django.test import Client

from tests.helpers import login_and_select_company, login_client


@pytest.mark.integration
@pytest.mark.django_db
def test_root_is_dashboard_list_for_viewer(api_client, viewer_user, btc_company):
    login_and_select_company(api_client, "pytest_viewer", btc_company)
    response = api_client.get("/")
    assert response.status_code == 200
    assert b"db-grid" in response.content or b"empty-state" in response.content


@pytest.mark.integration
@pytest.mark.django_db
def test_upload_url_requires_auth(api_client):
    response = api_client.get("/upload/")
    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.integration
@pytest.mark.django_db
def test_legacy_dashboards_redirects_home(api_client, viewer_user, btc_company):
    login_and_select_company(api_client, "pytest_viewer", btc_company)
    response = api_client.get("/dashboards/")
    assert response.status_code == 302
    assert response.url == "/"


@pytest.mark.integration
@pytest.mark.django_db
def test_no_perm_user_root_redirects_profile(api_client, no_perm_user, btc_company):
    login_and_select_company(api_client, "pytest_no_perm", btc_company)
    response = api_client.get("/")
    assert response.status_code == 302
    assert "/profile/" in response.url
