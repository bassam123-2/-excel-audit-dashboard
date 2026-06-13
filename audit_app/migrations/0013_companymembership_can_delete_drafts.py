from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audit_app", "0012_companymembership_can_view_own_only"),
    ]

    operations = [
        migrations.AddField(
            model_name="companymembership",
            name="can_delete_drafts",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Remove draft dashboards in this company only. "
                    "Published dashboards cannot be deleted."
                ),
                verbose_name="Can delete draft dashboards",
            ),
        ),
    ]
