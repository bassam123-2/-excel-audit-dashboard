"""Admin user form and change/add view regression tests."""
from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from audit_app.admin_forms import AdminUserChangeForm, MandatoryPasswordAdminCreationForm
from tests.factories import make_user


@pytest.fixture
def admin_client(db):
    user = User.objects.create_superuser("myadmin", "myadmin@test.com", "Test@1234!")
    client = Client()
    client.force_login(user)
    return client


def _membership_formset_fields(*, total: str = "0") -> dict[str, str]:
    return {
        "company_memberships-TOTAL_FORMS": total,
        "company_memberships-INITIAL_FORMS": "0",
        "company_memberships-MIN_NUM_FORMS": "0",
        "company_memberships-MAX_NUM_FORMS": "1000",
    }


def _admin_save_fields() -> dict[str, str]:
    return {"_save": "Save"}


def _assert_admin_post_redirect(response) -> None:
    if response.status_code == 302:
        return
    adminform = response.context.get("adminform") if response.context else None
    details = []
    if adminform:
        details.append(f"form={adminform.form.errors}")
        details.append(f"non_form={adminform.form.non_field_errors()}")
    for index, formset in enumerate(response.context.get("inline_admin_formsets", [])):
        if formset.formset.errors:
            details.append(f"formset[{index}]={formset.formset.errors}")
        if formset.formset.non_form_errors():
            details.append(f"formset_nf[{index}]={formset.formset.non_form_errors()}")
    pytest.fail(
        f"Expected redirect, got {response.status_code}. "
        + (" | ".join(details) if details else "no admin context")
    )


@pytest.mark.django_db
def test_creation_form_excludes_workflow_email_field():
    form = MandatoryPasswordAdminCreationForm()
    assert "receive_workflow_emails" not in form.fields


@pytest.mark.django_db
def test_change_form_non_superuser_excludes_workflow_email_field(btc_company):
    user = make_user("regular_admin_user", email="regular@example.com")
    form = AdminUserChangeForm(instance=user)
    assert "receive_workflow_emails" not in form.fields


@pytest.mark.django_db
def test_change_form_superuser_includes_workflow_email_field():
    user = make_user("super_admin_user", email="super@example.com")
    user.is_superuser = True
    user.save(update_fields=["is_superuser"])
    form = AdminUserChangeForm(instance=user)
    assert "receive_workflow_emails" in form.fields


@pytest.mark.django_db
def test_creation_form_save_commit_false_does_not_touch_profile():
    form = MandatoryPasswordAdminCreationForm(
        data={
            "username": "unsaved_user",
            "password1": "ComplexPass1!",
            "password2": "ComplexPass1!",
            "email": "unsaved@example.com",
        }
    )
    assert form.is_valid(), form.errors
    user = form.save(commit=False)
    assert user.pk is None


@pytest.mark.django_db
def test_admin_add_user_succeeds(admin_client):
    response = admin_client.post(
        reverse("admin:auth_user_add"),
        {
            "username": "added_via_admin",
            "password1": "ComplexPass1!",
            "password2": "ComplexPass1!",
            "email": "added@example.com",
            "first_name": "Added",
            "last_name": "User",
            "job_title": "Reviewer",
            "password_expiry_enabled": "on",
            "is_active": "on",
            **_admin_save_fields(),
            **_membership_formset_fields(),
        },
    )
    _assert_admin_post_redirect(response)
    user = User.objects.get(username="added_via_admin")
    assert user.email == "added@example.com"
    assert user.profile.job_title == "Reviewer"


@pytest.mark.django_db
def test_admin_change_non_superuser_page_loads(admin_client, btc_company):
    user = make_user("edit_me", email="edit_me@example.com")
    response = admin_client.get(reverse("admin:auth_user_change", args=[user.pk]))
    assert response.status_code == 200
    content = response.content.decode()
    assert 'name="receive_workflow_emails"' not in content
    assert 'id="id_receive_workflow_emails"' not in content


@pytest.mark.django_db
def test_admin_change_superuser_shows_workflow_email_field(admin_client):
    user = make_user("edit_super", email="edit_super@example.com")
    user.is_superuser = True
    user.is_staff = True
    user.save(update_fields=["is_superuser", "is_staff"])
    response = admin_client.get(reverse("admin:auth_user_change", args=[user.pk]))
    assert response.status_code == 200
    content = response.content.decode()
    assert 'name="receive_workflow_emails"' in content


@pytest.mark.django_db
def test_admin_change_superuser_enable_workflow_emails(admin_client):
    add_response = admin_client.post(
        reverse("admin:auth_user_add"),
        {
            "username": "new_super",
            "password1": "ComplexPass1!",
            "password2": "ComplexPass1!",
            "email": "new_super@example.com",
            "password_expiry_enabled": "on",
            "is_active": "on",
            **_admin_save_fields(),
            **_membership_formset_fields(),
        },
    )
    _assert_admin_post_redirect(add_response)
    user = User.objects.get(username="new_super")
    assert user.is_superuser is False

    change_response = admin_client.post(
        reverse("admin:auth_user_change", args=[user.pk]),
        {
            "username": user.username,
            "email": user.email,
            "password_expiry_enabled": "on",
            "receive_workflow_emails": "on",
            "is_active": "on",
            "is_staff": "on",
            "is_superuser": "on",
            **_admin_save_fields(),
            **_membership_formset_fields(),
        },
    )
    _assert_admin_post_redirect(change_response)
    user.refresh_from_db()
    assert user.is_superuser is True
    user.profile.refresh_from_db()
    assert user.profile.receive_workflow_emails is True
