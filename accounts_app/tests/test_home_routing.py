"""Tests for resolve_default_home navigation."""
from __future__ import annotations

import pytest
from django.urls import reverse

from accounts_app.navigation import resolve_default_home
from tests.factories import make_membership, make_user


@pytest.mark.unit
@pytest.mark.django_db
def test_resolve_default_home_dashboard_viewer(btc_company, viewer_user):
    assert resolve_default_home(viewer_user) == reverse("dashboard_list")


@pytest.mark.unit
@pytest.mark.django_db
def test_resolve_default_home_no_permissions(btc_company, no_perm_user):
    assert resolve_default_home(no_perm_user) == reverse("profile")


@pytest.mark.unit
@pytest.mark.django_db
def test_resolve_default_home_multi_company(btc_company, nat_company):
    user = make_user("multi_home")
    make_membership(user, btc_company, can_upload=True)
    make_membership(user, nat_company, can_upload=True)
    assert resolve_default_home(user) == reverse("select_company")
