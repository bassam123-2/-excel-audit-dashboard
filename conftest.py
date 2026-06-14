"""Project-wide pytest fixtures (loaded from repository root)."""
from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.test import Client

from audit_app.models import Company, Dashboard, DashboardStatus
from tests.factories import make_membership, make_user


@pytest.fixture
def api_client():
    return Client()


@pytest.fixture
def btc_company(db):
    company, _ = Company.objects.get_or_create(
        code="BTC",
        defaults={"name": "BTC", "excel_company_names": ["BTC"]},
    )
    company.ensure_attachment_settings()
    return company


@pytest.fixture
def nat_company(db):
    company, _ = Company.objects.get_or_create(
        code="NAT",
        defaults={"name": "NAT", "excel_company_names": ["NAT"]},
    )
    company.ensure_attachment_settings()
    return company


@pytest.fixture
def uploader_user(btc_company):
    user = make_user("pytest_uploader", email="uploader@example.com")
    make_membership(user, btc_company, can_upload=True, can_view=True)
    return user


@pytest.fixture
def viewer_user(btc_company):
    user = make_user("pytest_viewer", email="viewer@example.com")
    make_membership(user, btc_company, can_view=True)
    return user


@pytest.fixture
def no_perm_user(btc_company):
    user = make_user("pytest_no_perm", email="noperm@example.com")
    make_membership(user, btc_company)
    return user


@pytest.fixture
def superuser(btc_company):
    user = User.objects.create_superuser(
        "pytest_super", "super@example.com", "Test@1234"
    )
    user.profile.two_factor_enabled = False
    user.profile.save(update_fields=["two_factor_enabled"])
    return user


@pytest.fixture
def draft_dashboard(btc_company, uploader_user):
    return Dashboard.objects.create(
        name="Draft Board",
        report_id="rid-draft-pytest",
        company=btc_company,
        created_by=uploader_user,
        status=DashboardStatus.DRAFT,
    )
