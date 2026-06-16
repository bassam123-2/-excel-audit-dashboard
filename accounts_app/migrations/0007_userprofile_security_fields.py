"""Add must_change_password_on_login; require job_title on UserProfile."""
from __future__ import annotations

from django.db import migrations, models


def fill_empty_job_titles(apps, schema_editor):
    UserProfile = apps.get_model("accounts_app", "UserProfile")
    UserProfile.objects.filter(job_title="").update(job_title="—")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts_app", "0006_userprofile_receive_workflow_emails"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="must_change_password_on_login",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "When enabled, the user is redirected to change their password "
                    "before accessing the application."
                ),
                verbose_name="Must change password on next sign-in",
            ),
        ),
        migrations.RunPython(fill_empty_job_titles, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="userprofile",
            name="job_title",
            field=models.CharField(
                blank=False,
                help_text="The user's job title or position.",
                max_length=128,
                verbose_name="Job title",
            ),
        ),
    ]
