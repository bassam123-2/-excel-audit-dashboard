"""Project timezone configuration and middleware."""

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

import pytest
from django.contrib.auth.models import Permission, User
from django.template import Context, Template
from django.test import Client, RequestFactory
from django.urls import reverse

from accounts_app.middleware import ProjectTimezoneMiddleware
from accounts_app.models import ProjectSecuritySettings
from accounts_app.services.project_timezone import (
    get_project_timezone_name,
    invalidate_project_timezone_cache,
    project_localtime,
)


@pytest.mark.django_db
def test_project_timezone_setting_is_cached():
    settings_obj = ProjectSecuritySettings.load()
    settings_obj.timezone = "Asia/Riyadh"
    settings_obj.save()
    invalidate_project_timezone_cache()

    assert get_project_timezone_name() == "Asia/Riyadh"


@pytest.mark.django_db
def test_project_localtime_uses_configured_zone():
    settings_obj = ProjectSecuritySettings.load()
    settings_obj.timezone = "Asia/Riyadh"
    settings_obj.save()
    invalidate_project_timezone_cache()

    utc_dt = datetime(2026, 7, 9, 12, 0, tzinfo=dt_timezone.utc)
    local_dt = project_localtime(utc_dt)

    assert local_dt.tzinfo is not None
    assert local_dt.hour == 15
    assert local_dt.strftime("%Y/%m/%d %H:%M") == "2026/07/09 15:00"


@pytest.mark.django_db
def test_middleware_activates_timezone_for_templates():
    settings_obj = ProjectSecuritySettings.load()
    settings_obj.timezone = "Asia/Riyadh"
    settings_obj.save()
    invalidate_project_timezone_cache()

    rendered = None

    def get_response(request):
        nonlocal rendered
        rendered = Template("{{ value|date:'Y/m/d H:i' }}").render(
            Context(
                {
                    "value": datetime(2026, 7, 9, 12, 0, tzinfo=dt_timezone.utc),
                }
            )
        )
        return None

    factory = RequestFactory()
    middleware = ProjectTimezoneMiddleware(get_response)
    middleware(factory.get("/"))

    assert rendered == "2026/07/09 15:00"


@pytest.mark.django_db
def test_admin_security_settings_shows_timezone_field(admin_client):
    settings_obj = ProjectSecuritySettings.load()
    url = reverse(
        "admin:accounts_app_projectsecuritysettings_change",
        args=[settings_obj.pk],
    )
    response = admin_client.get(url)
    html = response.content.decode()

    assert response.status_code == 200
    assert "timezone" in html
    assert "Date and time" in html


@pytest.mark.django_db
def test_timezone_field_readonly_without_manage_permission(db):
    settings_obj = ProjectSecuritySettings.load()
    user = User.objects.create_user(
        "tz_viewer",
        "tz_viewer@test.com",
        "Test@1234!",
        first_name="TZ",
        last_name="Viewer",
    )
    user.is_staff = True
    user.user_permissions.add(
        Permission.objects.get(
            codename="change_projectsecuritysettings",
            content_type__app_label="accounts_app",
            content_type__model="projectsecuritysettings",
        )
    )
    user.save()

    client = Client()
    client.force_login(user)
    url = reverse(
        "admin:accounts_app_projectsecuritysettings_change",
        args=[settings_obj.pk],
    )
    response = client.get(url)
    html = response.content.decode()

    assert response.status_code == 200
    assert "readonly" in html or "disabled" in html
