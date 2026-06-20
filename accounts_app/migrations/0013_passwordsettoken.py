"""Add PasswordSetToken for one-time set-password email links."""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts_app", "0012_projectsecuritysettings"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PasswordSetToken",
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
                ("token_hash", models.CharField(db_index=True, max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="password_set_tokens",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="User",
                    ),
                ),
            ],
            options={
                "verbose_name": "Password set token",
                "verbose_name_plural": "Password set tokens",
                "indexes": [
                    models.Index(
                        fields=["user", "used_at"],
                        name="accounts_ap_user_id_6a8f2c_idx",
                    ),
                    models.Index(
                        fields=["expires_at"],
                        name="accounts_ap_expires_91b4e1_idx",
                    ),
                ],
            },
        ),
    ]
