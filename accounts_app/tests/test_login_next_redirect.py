"""Login / 2FA redirect preservation tests."""
from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from tests.factories import make_membership, make_user


@pytest.mark.django_db
def test_authenticated_login_with_next_redirects_to_target(btc_company, viewer_user):
    client = Client()
    client.force_login(viewer_user)
    target = reverse("dashboard_list")
    response = client.get(f"{reverse('login')}?next={target}")
    assert response.status_code == 302
    assert response.url == target


@pytest.mark.django_db
def test_failed_login_preserves_next_in_form(btc_company):
    user = make_user("next_fail_user", email="next_fail@example.com", password="Test@1234")
    make_membership(user, btc_company, can_view=True)
    client = Client()
    target = reverse("dashboard_list")
    response = client.post(
        reverse("login"),
        {
            "username": "next_fail_user",
            "password": "wrong-password",
            "next": target,
        },
    )
    assert response.status_code == 200
    assert f'value="{target}"' in response.content.decode()


@pytest.mark.django_db
def test_login_success_with_next_redirects(btc_company):
    user = make_user("next_ok_user", email="next_ok@example.com", password="Test@1234")
    make_membership(user, btc_company, can_view=True)
    user.profile.two_factor_enabled = False
    user.profile.save(update_fields=["two_factor_enabled"])
    client = Client()
    target = reverse("dashboard_list")
    response = client.post(
        reverse("login"),
        {
            "username": "next_ok_user",
            "password": "Test@1234",
            "next": target,
        },
    )
    assert response.status_code == 302
    assert response.url == target


@pytest.mark.django_db
def test_protected_page_redirects_unauthenticated_with_next():
    client = Client()
    target_path = reverse("dashboard_list")
    response = client.get(target_path)
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))
    assert "next=" in response.url
    assert target_path in response.url
