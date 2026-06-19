"""Admin user form and change/add view regression tests."""
from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from audit_app.admin_forms import AdminUserChangeForm, MandatoryPasswordAdminCreationForm
from tests.factories import make_user


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
def test_creation_form_two_factor_enabled_by_default():
    form = MandatoryPasswordAdminCreationForm()
    assert form.fields["two_factor_enabled"].initial is True


@pytest.mark.django_db
def test_new_user_profile_two_factor_default_true():
    user = User.objects.create_user(
        username="new2fa",
        email="new2fa@example.com",
        password="Str0ng!Pass",
        first_name="New",
        last_name="User",
    )
    user.profile.job_title = "Analyst"
    user.profile.save(update_fields=["job_title"])
    assert user.profile.two_factor_enabled is True


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
            "first_name": "Unsaved",
            "last_name": "User",
            "job_title": "Role",
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
            "first_name": "New",
            "last_name": "Super",
            "job_title": "Lead",
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
            "first_name": "New",
            "last_name": "Super",
            "job_title": "Lead",
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


@pytest.mark.regression
@pytest.mark.django_db
def test_admin_add_user_with_send_credentials_email(admin_client):
    from unittest.mock import patch

    from audit_app.admin import ProtectedUserAdmin

    with patch.object(ProtectedUserAdmin, "_send_credentials_email", return_value=True) as send_mock:
        response = admin_client.post(
            reverse("admin:auth_user_add"),
            {
                "username": "email_on_create",
                "password1": "ComplexPass1!",
                "password2": "ComplexPass1!",
                "email": "email_on_create@example.com",
                "first_name": "Email",
                "last_name": "OnCreate",
                "job_title": "Role",
                "password_expiry_enabled": "on",
                "send_credentials_email": "on",
                "is_active": "on",
                **_admin_save_fields(),
                **_membership_formset_fields(),
            },
        )
    _assert_admin_post_redirect(response)
    user = User.objects.get(username="email_on_create")
    assert user.profile.must_change_password_on_login is True
    send_mock.assert_called_once()
    assert send_mock.call_args[0][2] == "ComplexPass1!"


@pytest.mark.regression
@pytest.mark.django_db
def test_admin_add_user_page_loads_password_rules_script(admin_client):
    response = admin_client.get(reverse("admin:auth_user_add"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "password_rules.js" in html
    assert "user_form" in html


@pytest.mark.regression
@pytest.mark.django_db
def test_admin_add_user_page_shows_send_credentials_checkbox(admin_client):
    response = admin_client.get(reverse("admin:auth_user_add"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "send_credentials_email" in html
    assert "Send new password by email" in html or "إرسال" in html


@pytest.mark.regression
@pytest.mark.django_db
def test_admin_set_password_succeeds(admin_client, btc_company):
    user = make_user("pw_reset_target", email="pwreset@example.com")
    url = reverse("admin:auth_user_set_password", args=[user.pk])
    response = admin_client.post(
        url,
        {
            "password1": "NewComplex1!",
            "password2": "NewComplex1!",
            "send_credentials_email": "on",
        },
    )
    assert response.status_code == 302, response.content.decode()[:500]
    user.refresh_from_db()
    assert user.check_password("NewComplex1!")
    user.profile.refresh_from_db()
    assert user.profile.must_change_password_on_login is True


@pytest.mark.django_db
def test_admin_user_changelist_renders_v2_layout(admin_client):
    response = admin_client.get(reverse("admin:auth_user_changelist"), follow=True)
    assert response.status_code == 200
    assert "deleted=active" in response.request["PATH_INFO"] + "?" + response.request.get("QUERY_STRING", "")
    html = response.content.decode()
    assert "admin-cl-v2__header-row" in html
    assert "admin-cl-v2__badge" not in html
    assert "admin-cl-v2__stats" in html
    assert "admin-cl-v2__quick-actions" in html
    assert "Enable email 2FA for selected users" in html
    assert 'data-cl-v2-quick-action="enable_two_factor_selected"' in html
    assert 'data-cl-v2-quick-action="enable_two_factor_all"' not in html
    assert "admin-cl-v2__table-panel" in html
    assert "admin-cl-v2__filters-panel" in html
    assert "admin_changelist_v2.css" in html
    assert "admin_changelist_v2.js" in html


@pytest.mark.django_db
def test_admin_user_changelist_stats_match_filtered_results(admin_client):
    make_user("stats_alpha", email="stats_alpha@example.com")
    make_user("stats_beta", email="stats_beta@example.com")
    url = reverse("admin:auth_user_changelist")
    response = admin_client.get(f"{url}?deleted=active&q=stats_alpha", follow=True)
    assert response.status_code == 200
    html = response.content.decode()
    assert 'class="admin-cl-v2__stat-value">1</p>' in html or ">1<" in html


@pytest.mark.django_db
def test_admin_user_changelist_deleted_all_includes_soft_deleted(admin_client):
    active = make_user("active_list_user", email="active_list@example.com")
    deleted = make_user("deleted_list_user", email="deleted_list@example.com")
    deleted.profile.is_deleted = True
    deleted.profile.save(update_fields=["is_deleted"])
    deleted.is_active = False
    deleted.save(update_fields=["is_active"])

    url = reverse("admin:auth_user_changelist")
    response = admin_client.get(f"{url}?deleted=all", follow=True)
    assert response.status_code == 200
    html = response.content.decode()
    assert active.username in html
    assert deleted.username in html


@pytest.mark.django_db
def test_admin_user_quick_action_enable_password_expiry_selected(admin_client):
    user = make_user("expiry_selected_user", email="expiry_selected@example.com")
    url = reverse("admin:auth_user_changelist") + "?deleted=active"
    response = admin_client.post(
        url,
        {
            "action": "enable_password_expiry_selected",
            "_selected_action": [str(user.pk)],
            "index": "0",
        },
        follow=True,
    )
    assert response.status_code == 200
    assert "password expiry enabled" in response.content.decode().lower()
    user.profile.refresh_from_db()
    assert user.profile.password_expiry_enabled is True


@pytest.mark.django_db
def test_admin_user_quick_actions_selected_buttons_present(admin_client):
    changelist = reverse("admin:auth_user_changelist") + "?deleted=active"
    response = admin_client.get(changelist, follow=True)
    html = response.content.decode()
    assert 'data-cl-v2-quick-action="enable_two_factor_selected"' in html
    assert 'data-requires-selection="1"' in html
    for action_name in (
        "enable_two_factor_selected",
        "disable_two_factor_selected",
        "enable_password_expiry_selected",
        "disable_password_expiry_selected",
    ):
        assert f'data-cl-v2-quick-action="{action_name}"' in html


@pytest.mark.django_db
def test_admin_user_delete_modal_on_change_form(admin_client):
    user = make_user("delete_modal_user", email="delete_modal@example.com")
    response = admin_client.get(reverse("admin:auth_user_change", args=[user.pk]))
    assert response.status_code == 200
    html = response.content.decode()
    assert "admin-user-delete-modal" in html
    assert "admin_user_delete_modal.js" in html
    assert "admin_user_delete_modal.css" in html
    assert "Yes, remove user" in html or "نعم، إزالة المستخدم" in html


@pytest.mark.django_db
def test_admin_delete_modal_renders_in_arabic(admin_client):
    user = make_user("delete_modal_ar", email="delete_modal_ar@example.com")
    admin_user = User.objects.get(username="myadmin")
    admin_user.profile.preferred_language = "ar"
    admin_user.profile.save(update_fields=["preferred_language"])
    response = admin_client.get(reverse("admin:auth_user_change", args=[user.pk]))
    assert response.status_code == 200
    html = response.content.decode()
    assert "هل أنت متأكد من إزالة المستخدم" in html
    assert "نعم، إزالة المستخدم" in html
    assert "إلغاء" in html
    assert "سيتم إلغاء تفعيل الحساب" in html


@pytest.mark.django_db
def test_admin_change_soft_deleted_user_omits_delete_modal(admin_client):
    user = make_user("deleted_modal_user", email="deleted_modal@example.com")
    user.profile.is_deleted = True
    user.profile.save(update_fields=["is_deleted"])
    user.is_active = False
    user.save(update_fields=["is_active"])
    response = admin_client.get(reverse("admin:auth_user_change", args=[user.pk]))
    assert response.status_code == 200
    html = response.content.decode()
    assert "admin-user-delete-modal" not in html


@pytest.mark.django_db
def test_admin_soft_delete_user_via_post(admin_client):
    user = make_user("soft_delete_target", email="softdel@example.com")
    delete_url = reverse("admin:auth_user_delete", args=[user.pk])
    response = admin_client.post(delete_url, {"post": "yes"})
    assert response.status_code == 302
    user.refresh_from_db()
    user.profile.refresh_from_db()
    assert user.profile.is_deleted is True
    assert user.is_active is False
