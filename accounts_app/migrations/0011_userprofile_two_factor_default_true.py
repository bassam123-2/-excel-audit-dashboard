from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts_app", "0010_userprofile_preferred_theme"),
    ]

    operations = [
        migrations.AlterField(
            model_name="userprofile",
            name="two_factor_enabled",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "When enabled, a one-time code is sent by email at sign-in. "
                    "Enabled by default for new users — disable per user from the admin if needed."
                ),
                verbose_name="Email two-factor authentication",
            ),
        ),
    ]
