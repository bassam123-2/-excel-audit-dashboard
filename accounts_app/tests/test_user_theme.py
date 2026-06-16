"""Tests for UI theme: default light, session, and profile persistence."""
from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounts_app.models import UserProfile

User = get_user_model()


@pytest.mark.django_db
def test_anonymous_default_theme_is_light(client: Client):
    response = client.get(reverse("login"))
    assert response.status_code == 200
    assert response.context["ui_theme"] == "light"
    assert 'data-ui-theme="light"' in response.content.decode()


@pytest.mark.django_db
def test_anonymous_switch_theme_persists_in_session(client: Client):
    response = client.post(
        reverse("switch_theme"),
        {"theme": "dark"},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert response.status_code == 200
    assert json.loads(response.content)["theme"] == "dark"
    assert client.session["ui_theme"] == "dark"


@pytest.mark.django_db
def test_authenticated_user_uses_profile_preferred_theme(client: Client):
    user = User.objects.create_user(
        username="themeuser",
        email="themeuser@example.com",
        password="Str0ng!Pass",
        first_name="Theme",
        last_name="User",
    )
    profile = UserProfile.objects.get(user=user)
    profile.job_title = "Analyst"
    profile.preferred_theme = "dark"
    profile.save(update_fields=["job_title", "preferred_theme"])

    client.force_login(user)
    response = client.get(reverse("profile"))
    assert response.status_code == 200
    assert response.context["ui_theme"] == "dark"
    assert 'data-ui-theme="dark"' in response.content.decode()


@pytest.mark.django_db
def test_authenticated_switch_theme_updates_profile(client: Client):
    user = User.objects.create_user(
        username="themeswitch",
        email="themeswitch@example.com",
        password="Str0ng!Pass",
        first_name="Switch",
        last_name="Theme",
    )
    profile = UserProfile.objects.get(user=user)
    profile.job_title = "Analyst"
    profile.preferred_theme = "light"
    profile.save(update_fields=["job_title", "preferred_theme"])

    client.force_login(user)
    response = client.post(
        reverse("switch_theme"),
        {"theme": "dark"},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert response.status_code == 200

    profile.refresh_from_db()
    assert profile.preferred_theme == "dark"
    assert client.session["ui_theme"] == "dark"


@pytest.mark.django_db
def test_login_applies_profile_theme_to_session(client: Client):
    user = User.objects.create_user(
        username="logintheme",
        email="logintheme@example.com",
        password="Str0ng!Pass",
        first_name="Login",
        last_name="Theme",
    )
    profile = UserProfile.objects.get(user=user)
    profile.job_title = "Analyst"
    profile.preferred_theme = "dark"
    profile.save(update_fields=["job_title", "preferred_theme"])

    session = client.session
    session["ui_theme"] = "light"
    session.save()

    assert client.login(username="logintheme", password="Str0ng!Pass")

    response = client.get(reverse("profile"))
    assert response.context["ui_theme"] == "dark"
    assert client.session["ui_theme"] == "dark"


@pytest.mark.django_db
def test_new_user_profile_defaults_to_light_theme():
    user = User.objects.create_user(
        username="newtheme",
        email="newtheme@example.com",
        password="Str0ng!Pass",
        first_name="New",
        last_name="User",
    )
    profile = UserProfile.objects.get(user=user)
    profile.job_title = "Analyst"
    profile.save(update_fields=["job_title"])
    assert profile.preferred_theme == "light"
