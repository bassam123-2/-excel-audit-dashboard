# Generated manually for ProjectSecuritySettings singleton.

from django.db import migrations, models

import accounts_app.models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts_app", "0011_userprofile_two_factor_default_true"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectSecuritySettings",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "otp_ttl_seconds",
                    models.PositiveIntegerField(
                        default=accounts_app.models.DEFAULT_OTP_TTL_SECONDS,
                        help_text=(
                            "How long email verification codes remain valid. "
                            "The resend cooldown uses the same duration. "
                            "Allowed range: 60–3600 seconds."
                        ),
                        verbose_name="OTP validity (seconds)",
                    ),
                ),
            ],
            options={
                "verbose_name": "Project security settings",
                "verbose_name_plural": "Project security settings",
            },
        ),
    ]
