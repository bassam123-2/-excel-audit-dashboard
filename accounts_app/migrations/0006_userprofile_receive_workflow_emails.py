from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts_app", "0005_userprofile_password_expiry_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="receive_workflow_emails",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Superuser accounts only. When enabled, this support account receives "
                    "dashboard pending-review, publish, and related workflow emails."
                ),
                verbose_name="Receive workflow notification emails",
            ),
        ),
    ]
