"""Upload page template auto-selection tests."""
from __future__ import annotations

import pytest
from django.test import Client

from audit_app.models import DashboardTemplateType


@pytest.mark.django_db
def test_upload_auto_selects_single_active_template(btc_company):
    DashboardTemplateType.objects.filter(is_deleted=False).update(is_active=False)
    DashboardTemplateType.objects.filter(code="IAD", is_deleted=False).update(is_active=True)

    from django.contrib.auth.models import User
    from audit_app.models import CompanyMembership

    user = User.objects.create_user(
        "single_tpl_uploader",
        password="Test@1234",
        email="single_tpl@example.com",
    )
    profile = user.profile
    profile.two_factor_enabled = False
    profile.job_title = "Uploader"
    profile.save(update_fields=["two_factor_enabled", "job_title"])
    CompanyMembership.objects.create(
        user=user, company=btc_company, can_upload=True
    )

    client = Client()
    client.post("/login/", {"username": "single_tpl_uploader", "password": "Test@1234"})
    client.post("/select-company/", {"company_id": btc_company.pk})
    response = client.get("/upload/")
    assert response.status_code == 200
    content = response.content.decode()
    iad = DashboardTemplateType.objects.get(code="IAD", is_deleted=False)
    assert iad.name in content
    assert "template-badge--locked" in content
    assert 'name="template_type"' in content
    assert "uploadDetailsSection" in content
    assert 'style="display:none;"' not in content.split("uploadDetailsSection")[1].split(">")[0]
