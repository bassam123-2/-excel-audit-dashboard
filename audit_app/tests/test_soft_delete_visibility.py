"""Soft-deleted records must stay hidden outside admin deleted filters."""
from __future__ import annotations

import pytest
from django.urls import reverse

from audit_app.company_access import user_companies, user_membership
from audit_app.models import Dashboard, DashboardStatus
from reports_app.dashboard_workflow import dashboards_queryset_for_user
from tests.factories import make_membership, make_user
from tests.helpers import login_and_select_company


@pytest.mark.django_db
def test_deleted_company_hidden_from_user_companies(btc_company):
    btc_company.is_deleted = True
    btc_company.is_active = False
    btc_company.save(update_fields=["is_deleted", "is_active"])

    user = make_user("company_scope_user")
    make_membership(user, btc_company)

    assert not user_companies(user).filter(pk=btc_company.pk).exists()


@pytest.mark.django_db
def test_deleted_company_membership_does_not_grant_access(btc_company):
    user = make_user("membership_scope_user")
    membership = make_membership(user, btc_company)
    membership.is_deleted = True
    membership.save(update_fields=["is_deleted"])

    assert user_membership(user, btc_company) is None


@pytest.mark.django_db
def test_deleted_dashboard_hidden_from_dashboard_list(api_client, superuser, btc_company):
    dashboard = Dashboard.objects.create(
        name="Hidden After Delete",
        report_id="rid-hidden-delete",
        company=btc_company,
        created_by=superuser,
        status=DashboardStatus.PUBLISHED,
        is_deleted=True,
    )
    login_and_select_company(api_client, "pytest_super", btc_company)
    qs = dashboards_queryset_for_user(superuser, btc_company)
    assert dashboard.pk not in qs.values_list("pk", flat=True)

    response = api_client.get("/")
    assert response.status_code == 200
    assert "Hidden After Delete" not in response.content.decode()


@pytest.mark.django_db
def test_deleted_company_dashboards_hidden_even_when_company_active_flag_wrong(
    api_client, superuser, btc_company
):
    btc_company.is_deleted = True
    btc_company.is_active = True
    btc_company.save(update_fields=["is_deleted", "is_active"])

    Dashboard.objects.create(
        name="Orphan Published",
        report_id="rid-orphan-published",
        company=btc_company,
        created_by=superuser,
        status=DashboardStatus.PUBLISHED,
    )
    login_and_select_company(api_client, "pytest_super", btc_company)
    qs = dashboards_queryset_for_user(superuser, btc_company)
    assert qs.count() == 0


@pytest.mark.django_db
def test_admin_company_restore_via_admin_action(admin_client, btc_company):
    btc_company.is_deleted = True
    btc_company.is_active = False
    btc_company.save(update_fields=["is_deleted", "is_active"])

    changelist_url = reverse("admin:audit_app_company_changelist")
    response = admin_client.post(
        f"{changelist_url}?deleted=deleted",
        {
            "action": "restore_selected",
            "select_across": "0",
            "index": "0",
            "_selected_action": [str(btc_company.pk)],
        },
    )
    assert response.status_code == 302
    btc_company.refresh_from_db()
    assert btc_company.is_deleted is False
    assert btc_company.is_active is True


@pytest.mark.django_db
def test_admin_cannot_reactivate_deleted_company_without_restore(admin_client, btc_company):
    btc_company.is_deleted = True
    btc_company.is_active = False
    btc_company.save(update_fields=["is_deleted", "is_active"])

    change_url = reverse("admin:audit_app_company_change", args=[btc_company.pk])
    page = admin_client.get(change_url)
    assert page.status_code == 200
    assert "Restore record" in page.content.decode() or "استعادة السجل" in page.content.decode()

    admin_client.post(
        change_url,
        {
            "code": btc_company.code,
            "name": btc_company.name,
            "company_kind": btc_company.company_kind,
            "excel_company_names": "[]",
            "is_active": "on",
            "use_workflow_v2": "",
            "notify_creator_on_publish": "",
            "_save": "Save",
        },
    )
    btc_company.refresh_from_db()
    assert btc_company.is_deleted is True
    assert btc_company.is_active is False
