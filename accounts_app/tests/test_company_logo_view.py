"""Tests for active-company logo in the app topbar."""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from audit_app.company_access import SESSION_ACTIVE_COMPANY_KEY
from tests.factories import make_membership, make_user
from tests.helpers import login_and_select_company


def _attach_logo(company) -> None:
    company.logo.save(
        "logo.png",
        SimpleUploadedFile("logo.png", b"\x89PNG\r\n\x1a\n", content_type="image/png"),
        save=True,
    )


@pytest.mark.django_db
def test_company_logo_view_returns_logo_for_member(client, btc_company):
    _attach_logo(btc_company)
    user = make_user("logo_user", email="logo@example.com")
    make_membership(user, btc_company, can_upload=True)
    login_and_select_company(client, "logo_user", btc_company)

    url = reverse("company_logo", args=[btc_company.pk])
    response = client.get(url)

    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


@pytest.mark.django_db
def test_company_logo_view_forbidden_for_other_company(client, btc_company, nat_company):
    _attach_logo(nat_company)
    user = make_user("btc_only", email="btc@example.com")
    make_membership(user, btc_company, can_upload=True)
    login_and_select_company(client, "btc_only", btc_company)

    response = client.get(reverse("company_logo", args=[nat_company.pk]))

    assert response.status_code == 403


@pytest.mark.django_db
def test_topbar_shows_company_logo_on_profile(client, btc_company):
    _attach_logo(btc_company)
    user = make_user("profile_logo", email="profile@example.com")
    make_membership(user, btc_company, can_upload=True)
    login_and_select_company(client, "profile_logo", btc_company)

    response = client.get(reverse("profile"))

    assert response.status_code == 200
    html = response.content.decode()
    assert reverse("company_logo", args=[btc_company.pk]) in html
    assert 'class="topbar-company-logo"' in html


@pytest.mark.django_db
def test_topbar_empty_company_until_selection(client, btc_company, nat_company):
    user = make_user("pending_select", email="pending@example.com")
    make_membership(user, btc_company, can_upload=True)
    make_membership(user, nat_company, can_upload=True)
    client.force_login(user)

    response = client.get(reverse("profile"))
    html = response.content.decode()

    assert response.status_code == 200
    assert 'class="topbar-company-logo"' not in html
    assert f'value="{btc_company.pk}" selected' not in html
    assert f'value="{nat_company.pk}" selected' not in html
    assert "Select company" in html or "اختر شركة" in html


@pytest.mark.django_db
def test_topbar_logo_url_follows_active_company(client, btc_company, nat_company):
    _attach_logo(btc_company)
    _attach_logo(nat_company)
    user = make_user("multi_logo", email="multi@example.com")
    make_membership(user, btc_company, can_upload=True)
    make_membership(user, nat_company, can_upload=True)
    client.force_login(user)

    session = client.session
    session[SESSION_ACTIVE_COMPANY_KEY] = btc_company.pk
    session.save()
    btc_html = client.get(reverse("profile")).content.decode()
    assert reverse("company_logo", args=[btc_company.pk]) in btc_html

    session[SESSION_ACTIVE_COMPANY_KEY] = nat_company.pk
    session.save()
    nat_html = client.get(reverse("profile")).content.decode()
    assert reverse("company_logo", args=[nat_company.pk]) in nat_html
