from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts_app", "0004_two_factor_optional"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="password_expiry_enabled",
            field=models.BooleanField(
                default=True,
                help_text="When enabled, the user must change their password every 180 days.",
                verbose_name="Require password change every 6 months",
            ),
        ),
    ]
