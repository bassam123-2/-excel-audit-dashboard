"""Admin project security settings v2 layout."""

from __future__ import annotations

import pytest
from django.urls import reverse

from accounts_app.models import ProjectSecuritySettings


@pytest.mark.django_db
def test_admin_security_settings_renders_v2_form_layout(admin_client):
    settings_obj = ProjectSecuritySettings.load()
    url = reverse(
        "admin:accounts_app_projectsecuritysettings_change",
        args=[settings_obj.pk],
    )
    response = admin_client.get(url)
    assert response.status_code == 200
    html = response.content.decode()
    assert "admin-cl-v2-form" in html
    assert "admin-cl-v2__header-row" in html
    assert "admin-cl-v2-form__panel" in html
    assert "admin_change_form_v2.css" in html
    assert "Project security settings" in html
    assert "Configure email OTP validity" in html
    assert "otp_ttl_minutes" in html
