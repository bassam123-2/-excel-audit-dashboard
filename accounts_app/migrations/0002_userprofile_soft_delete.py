from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts_app", "0001_add_user_profile_job_title"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Deleted at"),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="is_deleted",
            field=models.BooleanField(
                default=False,
                help_text="Soft-deleted users remain in the database but cannot sign in.",
                verbose_name="Deleted",
            ),
        ),
    ]
