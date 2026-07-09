from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audit_app", "0022_per_dashboard_viewers"),
    ]

    operations = [
        migrations.AddField(
            model_name="dashboard",
            name="user_edits_json",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Persisted audit plan table, cell colors, and review notes.",
                verbose_name="Dashboard user edits (JSON)",
            ),
        ),
    ]
