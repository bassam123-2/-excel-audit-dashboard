"""Per-template company membership nav and upload permissions."""
from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from audit_app.dashboard_template_codes import TEMPLATE_CODE_CD, TEMPLATE_CODE_IAD
from audit_app.models import CompanyMembershipTemplateAccess
from reports_app.dashboard_workflow import has_upload_perm
from tests.factories import make_membership, make_user


def _set_upload_only(membership, code: str) -> None:
    CompanyMembershipTemplateAccess.objects.filter(membership=membership).update(
        can_upload=False,
        can_assign_dashboard_viewers=False,
        can_view_own_only=False,
        can_review=False,
        can_delete_drafts=False,
    )
    CompanyMembershipTemplateAccess.objects.filter(
        membership=membership, template_code=code
    ).update(can_upload=True)


@pytest.mark.django_db
def test_legacy_membership_flags_map_to_internal_audit_only(btc_company):
    from audit_app.models import CompanyMembership

    user = make_user("legacy_uploader")
    membership = CompanyMembership.objects.create(
        user=user, company=btc_company, can_upload=True
    )
    iad = membership.template_accesses.get(template_code=TEMPLATE_CODE_IAD)
    cd = membership.template_accesses.get(template_code=TEMPLATE_CODE_CD)
    assert iad.can_upload is True
    assert cd.can_upload is False
    assert has_upload_perm(user, btc_company, TEMPLATE_CODE_IAD)
    assert has_upload_perm(user, btc_company, TEMPLATE_CODE_CD) is False


@pytest.mark.django_db
def test_iad_only_upload_hides_compliance_nav(btc_company):
    user = make_user("iad_only")
    membership = make_membership(user, btc_company, can_upload=True)
    _set_upload_only(membership, TEMPLATE_CODE_IAD)

    client = Client()
    client.force_login(user)
    client.post("/select-company/", {"company_id": btc_company.pk})
    response = client.get("/upload/?template=IAD")
    html = response.content.decode()
    assert response.status_code == 200
    assert "Internal Audit Dashboard" in html or "لوحة التدقيق الداخلي" in html
    assert 'href="/upload/?template=CD"' not in html
    assert 'href="/?template=CD"' not in html
    assert 'href="/upload/?template=IAD"' in html

    denied = client.get("/upload/?template=CD")
    assert denied.status_code == 302


@pytest.mark.django_db
def test_iad_only_cannot_post_compliance_upload(btc_company):
    user = make_user("iad_post")
    membership = make_membership(user, btc_company, can_upload=True)
    _set_upload_only(membership, TEMPLATE_CODE_IAD)

    client = Client()
    client.force_login(user)
    client.post("/select-company/", {"company_id": btc_company.pk})
    response = client.post(
        "/analyze/",
        {
            "dashboard_name": "CD Board",
            "icon": "bi-bar-chart-line-fill",
            "template_type": TEMPLATE_CODE_CD,
        },
    )
    assert response.status_code == 200
    assert has_upload_perm(user, btc_company, TEMPLATE_CODE_CD) is False


@pytest.mark.django_db
def test_dashboard_list_filters_by_template(btc_company, uploader_user):
    from audit_app.models import Dashboard, DashboardStatus

    Dashboard.objects.create(
        name="IAD One",
        report_id="rid-iad-nav",
        company=btc_company,
        created_by=uploader_user,
        status=DashboardStatus.DRAFT,
        template_type=TEMPLATE_CODE_IAD,
    )
    Dashboard.objects.create(
        name="CD One",
        report_id="rid-cd-nav",
        company=btc_company,
        created_by=uploader_user,
        status=DashboardStatus.DRAFT,
        template_type=TEMPLATE_CODE_CD,
    )
    client = Client()
    client.force_login(uploader_user)
    client.post("/select-company/", {"company_id": btc_company.pk})
    iad_page = client.get("/?template=IAD").content.decode()
    cd_page = client.get("/?template=CD").content.decode()
    assert "IAD One" in iad_page
    assert "CD One" not in iad_page
    assert "CD One" in cd_page
    assert "IAD One" not in cd_page
