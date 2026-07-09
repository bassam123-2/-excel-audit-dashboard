# Generated manually for project timezone setting.

from django.db import migrations, models

import accounts_app.models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts_app", "0015_enable_workflow_emails_for_regular_users"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectsecuritysettings",
            name="timezone",
            field=models.CharField(
                default=accounts_app.models.DEFAULT_PROJECT_TIMEZONE,
                help_text=(
                    "All dates and times shown in the application, admin panel, "
                    "and generated reports use this timezone."
                ),
                max_length=63,
                verbose_name="Project timezone",
            ),
        ),
        migrations.AlterModelOptions(
            name="projectsecuritysettings",
            options={
                "permissions": [
                    (
                        "manage_project_timezone",
                        "Can change project timezone",
                    ),
                ],
                "verbose_name": "Project security settings",
                "verbose_name_plural": "Project security settings",
            },
        ),
    ]
