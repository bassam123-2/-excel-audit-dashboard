"""Ensure all admin changelists use the v2 layout."""

from __future__ import annotations

import pytest
from django.urls import reverse

ADMIN_V2_CHANGE_LISTS = (
    ("admin:auth_group_changelist", {}),
    ("admin:auth_user_changelist", {"deleted": "active"}),
    ("admin:audit_app_company_changelist", {}),
    ("admin:audit_app_companymembership_changelist", {}),
    ("admin:audit_app_observationrecord_changelist", {}),
    ("admin:audit_app_dashboardrejectionlog_changelist", {}),
    ("admin:audit_app_dashboardtemplatetype_changelist", {}),
    ("admin:audit_app_dashboardworkflowinstance_changelist", {}),
    ("admin:audit_app_dashboard_changelist", {}),
    ("admin:audit_app_reportartifact_changelist", {}),
    ("admin:audit_app_uploadsession_changelist", {}),
    ("admin:audit_app_dashboardworkflowsteplog_changelist", {}),
    ("admin:audit_app_workflowtemplate_changelist", {}),
)


@pytest.mark.parametrize("url_name,query", ADMIN_V2_CHANGE_LISTS)
@pytest.mark.django_db
def test_admin_changelist_renders_v2_layout(admin_client, url_name, query):
    url = reverse(url_name)
    if query:
        url = f"{url}?{'&'.join(f'{k}={v}' for k, v in query.items())}"
    response = admin_client.get(url)
    assert response.status_code == 200, response.content[:500]
    html = response.content.decode()
    assert "admin-cl-v2__header-row" in html
    assert "admin-cl-v2__stats" in html
    assert "admin-cl-v2__table-panel" in html
    assert "admin_changelist_v2.css" in html
    assert "admin_changelist_v2.js" in html
    assert "Add New" in html
