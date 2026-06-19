"""Admin company changelist v2 layout tests."""

from __future__ import annotations

import pytest
from django.urls import reverse

from audit_app.models import COMPANY_KIND_MAIN, COMPANY_KIND_SUBSIDIARY, Company


@pytest.mark.django_db
def test_admin_company_changelist_renders_v2_layout(admin_client):
    response = admin_client.get(reverse("admin:audit_app_company_changelist"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "admin-cl-v2__header-row" in html
    assert "admin-cl-v2__stats" in html
    assert "admin-cl-v2__table-panel" in html
    assert "admin-cl-v2__filters-panel" in html
    assert "admin-cl-v2__quick-actions" not in html
    assert "admin_changelist_v2.css" in html
    assert "admin_changelist_v2.js" in html
    assert "Browse and manage all companies" in html
    assert "Search company code or name" in html


@pytest.mark.django_db
def test_admin_company_changelist_stats_match_filtered_results(admin_client, btc_company):
    Company.objects.create(code="filterco", name="Filter Co", company_kind=COMPANY_KIND_MAIN)
    Company.objects.create(
        code="subco",
        name="Sub Co",
        company_kind=COMPANY_KIND_SUBSIDIARY,
        parent=btc_company,
    )

    url = reverse("admin:audit_app_company_changelist")
    response = admin_client.get(f"{url}?q=filterco")
    assert response.status_code == 200
    html = response.content.decode()
    assert 'class="admin-cl-v2__stat-value">1</p>' in html
    assert "filterco" in html.lower()


@pytest.mark.django_db
def test_admin_company_changelist_active_filter_updates_stats(admin_client, btc_company):
    Company.objects.create(
        code="inactiveco",
        name="Inactive Co",
        company_kind=COMPANY_KIND_MAIN,
        is_active=False,
    )

    url = reverse("admin:audit_app_company_changelist")
    response = admin_client.get(f"{url}?is_active__exact=0")
    assert response.status_code == 200
    html = response.content.decode()
    assert "inactiveco" in html.lower()
    assert 'class="admin-cl-v2__stat-value">1</p>' in html
