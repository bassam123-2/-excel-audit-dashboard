"""Admin add/change form v2 layout tests."""

from __future__ import annotations

import pytest
from django.urls import reverse

from tests.factories import make_user


ADMIN_V2_FORM_PAGES = (
    ("admin:auth_user_add", {}),
    ("admin:auth_group_add", {}),
    ("admin:audit_app_company_add", {}),
    ("admin:audit_app_dashboard_add", {}),
)


@pytest.mark.parametrize("url_name,query", ADMIN_V2_FORM_PAGES)
@pytest.mark.django_db
def test_admin_add_form_renders_v2_layout(admin_client, url_name, query):
    url = reverse(url_name)
    if query:
        url = f"{url}?{'&'.join(f'{k}={v}' for k, v in query.items())}"
    response = admin_client.get(url)
    assert response.status_code == 200, response.content[:500]
    html = response.content.decode()
    assert "admin-cl-v2-form" in html
    assert "admin-cl-v2-form__panel" in html
    assert "admin_change_form_v2.css" in html
    assert "Add New" in html


@pytest.mark.django_db
def test_admin_user_change_form_renders_v2_layout(admin_client):
    user = make_user("form_v2_user", email="form_v2@example.com")
    url = reverse("admin:auth_user_change", args=[user.pk])
    response = admin_client.get(url)
    assert response.status_code == 200
    html = response.content.decode()
    assert "admin-cl-v2-form" in html
    assert "form_v2_user" in html
    assert "Update user profile" in html


@pytest.mark.django_db
def test_admin_company_change_form_renders_v2_layout(admin_client, btc_company):
    url = reverse("admin:audit_app_company_change", args=[btc_company.pk])
    response = admin_client.get(url)
    assert response.status_code == 200
    html = response.content.decode()
    assert "admin-cl-v2-form__panel" in html
    assert btc_company.code in html
