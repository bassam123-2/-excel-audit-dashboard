"""Admin user validation regression tests."""
from __future__ import annotations

import pytest

from audit_app.admin_forms import AdminUserChangeForm, MandatoryPasswordAdminCreationForm
from tests.factories import make_user


@pytest.mark.regression
@pytest.mark.django_db
def test_duplicate_email_rejected_on_create():
    make_user("existing", email="dup@example.com")
    form = MandatoryPasswordAdminCreationForm(
        data={
            "username": "other",
            "password1": "ComplexPass1!",
            "password2": "ComplexPass1!",
            "email": "dup@example.com",
            "first_name": "A",
            "last_name": "B",
            "job_title": "Role",
        }
    )
    assert not form.is_valid()
    assert "email" in form.errors


@pytest.mark.regression
@pytest.mark.django_db
def test_duplicate_email_rejected_on_change_other_user():
    make_user("owner", email="owner@example.com")
    other = make_user("other", email="other@example.com")
    form = AdminUserChangeForm(
        data={
            "username": other.username,
            "email": "owner@example.com",
            "first_name": "O",
            "last_name": "U",
            "job_title": "Role",
        },
        instance=other,
    )
    assert not form.is_valid()
    assert "email" in form.errors


@pytest.mark.regression
@pytest.mark.django_db
def test_required_fields_rejected_when_empty():
    form = MandatoryPasswordAdminCreationForm(
        data={
            "username": "x",
            "password1": "ComplexPass1!",
            "password2": "ComplexPass1!",
            "email": "x@example.com",
            "first_name": "",
            "last_name": "",
            "job_title": "",
        }
    )
    assert not form.is_valid()
    assert "first_name" in form.errors
    assert "last_name" in form.errors
    assert "job_title" in form.errors


@pytest.mark.regression
@pytest.mark.django_db
def test_username_with_spaces_rejected():
    form = MandatoryPasswordAdminCreationForm(
        data={
            "username": "bad name",
            "password1": "ComplexPass1!",
            "password2": "ComplexPass1!",
            "email": "spaces@example.com",
            "first_name": "A",
            "last_name": "B",
            "job_title": "Role",
        }
    )
    assert not form.is_valid()
    assert "username" in form.errors
