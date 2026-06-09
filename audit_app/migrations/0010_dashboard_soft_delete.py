from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("audit_app", "0009_dashboard_workflow"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="dashboard",
            name="is_deleted",
            field=models.BooleanField(db_index=True, default=False, verbose_name="Soft deleted"),
        ),
        migrations.AddField(
            model_name="dashboard",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Deleted at"),
        ),
        migrations.AddField(
            model_name="dashboard",
            name="deleted_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="deleted_dashboards",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Deleted by",
            ),
        ),
        migrations.AlterModelOptions(
            name="dashboard",
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    ("can_upload_files", "Can upload files and create dashboards"),
                    ("can_view_dashboards", "Can view dashboards"),
                    ("can_delete_dashboards", "Can remove and restore dashboards"),
                    ("can_review_dashboards", "Can approve or reject dashboards"),
                ],
                "verbose_name": "Dashboard",
                "verbose_name_plural": "Dashboards",
            },
        ),
    ]
