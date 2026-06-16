"""OTP resend cooldown tests."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth.models import User

from accounts_app.services.two_factor import (
    OTP_RESEND_COOLDOWN_SECONDS,
    get_resend_cooldown_remaining,
    initiate_two_factor,
    record_otp_sent,
)


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
def test_cooldown_constant_is_two_minutes():
    assert OTP_RESEND_COOLDOWN_SECONDS == 120
