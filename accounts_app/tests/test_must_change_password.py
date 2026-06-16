"""Must-change-password on first login after admin provisioning."""
from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse


@pytest.mark.regression
@pytest.mark.django_db
def test_must_change_password_redirects_to_profile():
    user = User.objects.create_user(
        "newhire",
        "newhire@example.com",
        "TempPass1!",
        first_name="New",
        last_name="Hire",
    )
    user.profile.job_title = "Analyst"
    user.profile.must_change_password_on_login = True
    user.profile.save(update_fields=["job_title", "must_change_password_on_login"])

    client = Client()
    client.force_login(user)
    response = client.get(reverse("dashboard_list"), follow=False)
    assert response.status_code == 302
    assert reverse("profile") in response.url
    assert "force_password=1" in response.url
