"""Dashboard soft-delete and undo for superuser."""
from __future__ import annotations

import pytest
from django.contrib.auth.models import User

from audit_app.models import Dashboard, DashboardStatus
from tests.factories import make_membership, make_user
from tests.helpers import login_and_select_company


@pytest.mark.integration
@pytest.mark.django_db
def test_superuser_delete_returns_json(api_client, superuser, draft_dashboard, btc_company):
    login_and_select_company(api_client, "pytest_super", btc_company)
    response = api_client.post(
        f"/dashboards/{draft_dashboard.pk}/delete/",
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["pk"] == draft_dashboard.pk
    draft_dashboard.refresh_from_db()
    assert draft_dashboard.is_deleted is True


@pytest.mark.integration
@pytest.mark.django_db
def test_superuser_can_delete_published_dashboard(api_client, superuser, btc_company, uploader_user):
    published = Dashboard.objects.create(
        name="Published Board",
        report_id="rid-published-pytest",
        company=btc_company,
        created_by=uploader_user,
        status=DashboardStatus.PUBLISHED,
    )
    login_and_select_company(api_client, "pytest_super", btc_company)
    response = api_client.post(
        f"/dashboards/{published.pk}/delete/",
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert response.status_code == 200
    published.refresh_from_db()
    assert published.is_deleted is True


@pytest.mark.integration
@pytest.mark.django_db
def test_superuser_restore_after_delete(api_client, superuser, draft_dashboard, btc_company):
    login_and_select_company(api_client, "pytest_super", btc_company)
    api_client.post(
        f"/dashboards/{draft_dashboard.pk}/delete/",
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    response = api_client.post(f"/dashboards/{draft_dashboard.pk}/restore/")
    assert response.status_code == 302
    draft_dashboard.refresh_from_db()
    assert draft_dashboard.is_deleted is False


@pytest.mark.integration
@pytest.mark.django_db
def test_non_super_cannot_delete_dashboard(api_client, btc_company):
    deleter = make_user("draft_deleter_test")
    make_membership(deleter, btc_company, can_delete_drafts=True)
    draft = Dashboard.objects.create(
        name="Deleter Draft",
        report_id="rid-deleter-draft",
        company=btc_company,
        created_by=deleter,
        status=DashboardStatus.DRAFT,
    )
    login_and_select_company(api_client, "draft_deleter_test", btc_company)
    response = api_client.post(f"/dashboards/{draft.pk}/delete/")
    assert response.status_code == 302
    assert "deleted=" not in response.url
    assert not Dashboard.objects.filter(pk=draft.pk, is_deleted=True).exists()


@pytest.mark.integration
@pytest.mark.django_db
def test_superuser_list_shows_delete_for_published(api_client, superuser, btc_company, uploader_user):
    Dashboard.objects.create(
        name="Published Visible",
        report_id="rid-pub-visible",
        company=btc_company,
        created_by=uploader_user,
        status=DashboardStatus.PUBLISHED,
    )
    login_and_select_company(api_client, "pytest_super", btc_company)
    response = api_client.get("/")
    assert response.status_code == 200
    html = response.content.decode()
    assert "js-super-delete-form" in html
    assert "db-card-delete-btn" in html
