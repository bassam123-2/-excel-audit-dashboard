"""Tests for UI language: default English, session, and profile persistence."""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounts_app.models import UserProfile

User = get_user_model()


@pytest.mark.django_db
def test_anonymous_default_language_is_english(client: Client):
    response = client.get(reverse("login"))
    assert response.status_code == 200
    assert response.context["lang"] == "en"
    assert response.context["dir"] == "ltr"


@pytest.mark.django_db
def test_anonymous_switch_language_persists_in_session(client: Client):
    response = client.get(reverse("switch_language"), {"lang": "ar", "next": "/login/"})
    assert response.status_code == 302
    assert client.session["ui_lang"] == "ar"

    follow = client.get(reverse("login"))
    assert follow.context["lang"] == "ar"
    assert follow.context["dir"] == "rtl"


@pytest.mark.django_db
def test_authenticated_user_uses_profile_preferred_language(client: Client):
    user = User.objects.create_user(
        username="languser",
        email="languser@example.com",
        password="Str0ng!Pass",
        first_name="Lang",
        last_name="User",
    )
    profile = UserProfile.objects.get(user=user)
    profile.job_title = "Analyst"
    profile.preferred_language = "ar"
    profile.save(update_fields=["job_title", "preferred_language"])

    client.force_login(user)
    response = client.get(reverse("profile"))
    assert response.status_code == 200
    assert response.context["lang"] == "ar"


@pytest.mark.django_db
def test_authenticated_switch_language_updates_profile(client: Client):
    user = User.objects.create_user(
        username="switchuser",
        email="switchuser@example.com",
        password="Str0ng!Pass",
        first_name="Switch",
        last_name="User",
    )
    profile = UserProfile.objects.get(user=user)
    profile.job_title = "Analyst"
    profile.preferred_language = "en"
    profile.save(update_fields=["job_title", "preferred_language"])

    client.force_login(user)
    response = client.get(reverse("switch_language"), {"lang": "ar", "next": "/profile/"})
    assert response.status_code == 302

    profile.refresh_from_db()
    assert profile.preferred_language == "ar"
    assert client.session["ui_lang"] == "ar"

    follow = client.get(reverse("profile"))
    assert follow.context["lang"] == "ar"


@pytest.mark.django_db
def test_login_applies_profile_language_to_session(client: Client):
    user = User.objects.create_user(
        username="loginlang",
        email="loginlang@example.com",
        password="Str0ng!Pass",
        first_name="Login",
        last_name="Lang",
    )
    profile = UserProfile.objects.get(user=user)
    profile.job_title = "Analyst"
    profile.preferred_language = "ar"
    profile.save(update_fields=["job_title", "preferred_language"])

    session = client.session
    session["ui_lang"] = "en"
    session.save()

    logged_in = client.login(username="loginlang", password="Str0ng!Pass")
    assert logged_in

    response = client.get(reverse("profile"))
    assert response.context["lang"] == "ar"
    assert client.session["ui_lang"] == "ar"
