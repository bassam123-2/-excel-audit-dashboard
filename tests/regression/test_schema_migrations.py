"""Regression: DB schema matches models (prevents OperationalError on login)."""
from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client
from django.urls import reverse

from accounts_app.models import UserProfile
from tests.factories import make_user
from tests.regression.schema_expectations import (
    REQUIRED_MIGRATION_APPS,
    REQUIRED_USERPROFILE_COLUMNS,
)


def _table_columns(table_name: str) -> set[str]:
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table_name)
    return {col.name for col in description}


@pytest.mark.regression
@pytest.mark.django_db
def test_accounts_app_migrations_fully_applied():
    """Fail fast when code expects columns that migrate has not created yet."""
    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    plan = executor.migration_plan(targets)
    pending = [migration for migration, _backward in plan if not _backward]
    pending_apps = {migration.app_label for migration in pending}
    unexpected = pending_apps.intersection(REQUIRED_MIGRATION_APPS)
    assert not unexpected, (
        "Pending migrations detected for: "
        + ", ".join(sorted(unexpected))
        + ". Run: python manage.py migrate"
    )


@pytest.mark.regression
@pytest.mark.django_db
def test_userprofile_table_has_required_columns():
    columns = _table_columns(UserProfile._meta.db_table)
    missing = REQUIRED_USERPROFILE_COLUMNS - columns
    assert not missing, f"Missing UserProfile columns in DB: {sorted(missing)}"


@pytest.mark.regression
@pytest.mark.django_db
def test_login_get_does_not_raise_schema_error():
    client = Client()
    response = client.get(reverse("login"))
    assert response.status_code == 200


@pytest.mark.regression
@pytest.mark.django_db
def test_login_post_loads_user_profile_without_operational_error(btc_company):
    user = make_user("login_schema_user", email="login_schema@example.com", password="Test@1234")
    user.profile.must_change_password_on_login = False
    user.profile.save(update_fields=["must_change_password_on_login"])

    client = Client()
    response = client.post(
        reverse("login"),
        {"username": user.username, "password": "Test@1234"},
    )
    assert response.status_code in (302, 200)
    if response.status_code == 302:
        follow = client.get(response.url)
        assert follow.status_code == 200


@pytest.mark.regression
@pytest.mark.django_db
def test_password_expiry_middleware_reads_profile(btc_company):
    user = make_user("mw_user", email="mw@example.com")
    client = Client()
    client.force_login(user)
    response = client.get(reverse("profile"))
    assert response.status_code == 200


@pytest.mark.regression
@pytest.mark.django_db
def test_must_change_password_column_readable_after_login(btc_company):
    user = make_user("mc_user", email="mc@example.com", password="Test@1234")
    user.profile.must_change_password_on_login = True
    user.profile.save(update_fields=["must_change_password_on_login"])

    client = Client()
    response = client.post(
        reverse("login"),
        {"username": user.username, "password": "Test@1234"},
    )
    assert response.status_code == 302
    assert reverse("profile") in response.url


@pytest.mark.regression
@pytest.mark.django_db
def test_user_profile_signal_creates_row_with_must_change_default():
    user = User.objects.create_user(
        "signal_user",
        "signal@example.com",
        "Test@1234",
        first_name="Sig",
        last_name="Nal",
    )
    profile = UserProfile.objects.get(user=user)
    assert profile.must_change_password_on_login is False
    assert "must_change_password_on_login" in _table_columns(UserProfile._meta.db_table)
