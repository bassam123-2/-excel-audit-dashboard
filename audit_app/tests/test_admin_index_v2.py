"""Admin dashboard index v2 layout tests."""

from __future__ import annotations

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_admin_index_renders_v2_layout(admin_client):
    response = admin_client.get(reverse("admin:index"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "admin-index-v2" in html
    assert "admin-index-v2__recent-card" in html
    assert "admin_index_v2.css" in html
    assert "Recent actions" in html
    assert 'id="content-related"' in html
    assert "admin-index-v2__apps" not in html


@pytest.mark.django_db
@pytest.mark.parametrize(
    "app_label",
    ("auth", "audit_app", "accounts_app"),
)
def test_admin_app_index_redirects_to_dashboard(admin_client, app_label):
    response = admin_client.get(f"/admin/{app_label}/", follow=False)
    assert response.status_code == 302
    assert response.url == reverse("admin:index")


@pytest.mark.django_db
def test_admin_sidebar_app_sections_are_not_links(admin_client):
    response = admin_client.get(reverse("admin:index"))
    html = response.content.decode()
    assert 'class="section section-label"' in html
    assert 'href="/admin/auth/" class="section"' not in html
    assert 'href="/admin/audit_app/" class="section"' not in html
