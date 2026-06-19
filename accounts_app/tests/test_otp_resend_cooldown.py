"""OTP resend cooldown tests."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth.models import User

from accounts_app.models import DEFAULT_OTP_TTL_SECONDS, ProjectSecuritySettings
from accounts_app.services.otp_settings import (
    get_otp_resend_cooldown_seconds,
    get_otp_ttl_seconds,
    invalidate_otp_settings_cache,
)
from accounts_app.services.two_factor import (
    get_resend_cooldown_remaining,
    initiate_two_factor,
    record_otp_sent,
)


@pytest.fixture(autouse=True)
def reset_project_otp_settings(db):
    settings_obj = ProjectSecuritySettings.load()
    settings_obj.otp_ttl_seconds = DEFAULT_OTP_TTL_SECONDS
    settings_obj.save(update_fields=["otp_ttl_seconds"])
    invalidate_otp_settings_cache()
    yield
    invalidate_otp_settings_cache()


@pytest.mark.django_db
def test_resend_cooldown_blocks_second_send():
    user = User.objects.create_user(
        "otp_user",
        "otp@example.com",
        "Test@1234!",
        first_name="Otp",
        last_name="User",
    )
    user.profile.job_title = "Tester"
    user.profile.save(update_fields=["job_title"])

    record_otp_sent(user.pk)
    assert get_resend_cooldown_remaining(user.pk) > 0

    with patch("ai_excel_dashboard.load_smtp_config", return_value={"host": "x"}):
        with patch("accounts_app.services.two_factor.send_otp_email_smtp"):
            with pytest.raises(ValueError, match="resend_cooldown"):
                initiate_two_factor(user, "en", is_resend=True)


@pytest.mark.unit
def test_resend_cooldown_matches_otp_ttl_by_default():
    assert get_otp_resend_cooldown_seconds() == DEFAULT_OTP_TTL_SECONDS
    assert get_otp_resend_cooldown_seconds() == get_otp_ttl_seconds()


@pytest.mark.django_db
def test_admin_otp_ttl_setting_updates_cooldown():
    settings_obj = ProjectSecuritySettings.load()
    settings_obj.otp_ttl_seconds = 300
    settings_obj.save()
    invalidate_otp_settings_cache()

    assert get_otp_ttl_seconds() == 300
    assert get_otp_resend_cooldown_seconds() == 300
