"""Admin dashboard index v2 layout tests."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from audit_app.models import COMPANY_KIND_MAIN, COMPANY_KIND_SUBSIDIARY, Company


@pytest.mark.django_db
def test_admin_index_renders_v2_layout(admin_client):
    response = admin_client.get(reverse("admin:index"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "admin-index-v2" in html
    assert "admin_index_v2.css" in html
    assert "admin-index-v2__stat-group" in html
    assert "Total companies" in html
    assert "Active main companies" in html
    assert "Active subsidiaries" in html
    assert "Total users" in html
    assert "Inactive users" in html
    assert "Users without 2FA" in html


@pytest.mark.django_db
def test_admin_index_stat_links_use_changelist_filters(admin_client):
    Company.objects.create(
        code="MAIN1",
        name="Main One",
        company_kind=COMPANY_KIND_MAIN,
        is_active=True,
    )
    Company.objects.create(
        code="SUB1",
        name="Sub One",
        company_kind=COMPANY_KIND_SUBSIDIARY,
        is_active=True,
        parent=Company.objects.get(code="MAIN1"),
    )
    User = get_user_model()
    active_user = User.objects.create_user(
        "active_idx",
        "active_idx@example.com",
        "Test@1234",
    )
    inactive_user = User.objects.create_user(
        "inactive_idx",
        "inactive_idx@example.com",
        "Test@1234",
    )
    inactive_user.is_active = False
    inactive_user.save(update_fields=["is_active"])
    no_2fa = User.objects.create_user(
        "no2fa_idx",
        "no2fa_idx@example.com",
        "Test@1234",
    )
    no_2fa.profile.two_factor_enabled = False
    no_2fa.profile.save(update_fields=["two_factor_enabled"])
    del active_user, inactive_user, no_2fa

    response = admin_client.get(reverse("admin:index"))
    html = response.content.decode()
    assert "/admin/audit_app/company/?deleted=active&amp;company_kind=main&amp;is_active=1" in html
    assert "/admin/audit_app/company/?deleted=active&amp;company_kind=subsidiary&amp;is_active=1" in html
    assert "/admin/auth/user/?deleted=active&amp;is_active=0" in html
    assert "/admin/auth/user/?deleted=active&amp;two_factor=no" in html


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


@pytest.mark.django_db
def test_admin_sidebar_app_section_order(admin_client):
    import re

    response = admin_client.get(reverse("admin:index"))
    html = response.content.decode()
    labels = re.findall(r'class="app-([\w_]+) module', html)
    relevant = [label for label in labels if label in ("auth", "audit_app", "accounts_app")]
    assert relevant == ["auth", "audit_app", "accounts_app"]


@pytest.mark.django_db
def test_admin_index_hides_company_stats_without_company_view_perm(client):
    from django.contrib.auth.models import Permission

    User = get_user_model()
    user = User.objects.create_user(
        "staff_users_only",
        "staff_users_only@example.com",
        "Test@1234",
        is_staff=True,
    )
    user.user_permissions.add(Permission.objects.get(codename="view_user"))
    client.force_login(user)

    response = client.get(reverse("admin:index"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "admin-index-v2__stat-group--users" in html
    assert "Total users" in html
    assert "admin-index-v2__stat-group--companies" not in html
    assert "Total companies" not in html


@pytest.mark.django_db
def test_admin_index_hides_user_stats_without_user_view_perm(client):
    from django.contrib.auth.models import Permission

    User = get_user_model()
    user = User.objects.create_user(
        "staff_companies_only",
        "staff_companies_only@example.com",
        "Test@1234",
        is_staff=True,
    )
    user.user_permissions.add(Permission.objects.get(codename="view_company"))
    client.force_login(user)

    response = client.get(reverse("admin:index"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "admin-index-v2__stat-group--companies" in html
    assert "Total companies" in html
    assert "admin-index-v2__stat-group--users" not in html
    assert "Total users" not in html
