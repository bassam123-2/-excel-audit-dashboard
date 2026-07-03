from django.db import migrations


def enable_workflow_emails_for_regular_users(apps, schema_editor):
    UserProfile = apps.get_model("accounts_app", "UserProfile")
    UserProfile.objects.filter(user__is_superuser=False).update(
        receive_workflow_emails=True
    )


class Migration(migrations.Migration):
    dependencies = [
        (
            "accounts_app",
            "0014_rename_accounts_ap_user_id_6a8f2c_idx_accounts_ap_user_id_edb777_idx_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(
            enable_workflow_emails_for_regular_users,
            migrations.RunPython.noop,
        ),
    ]
