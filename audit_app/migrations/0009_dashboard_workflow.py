from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def publish_existing_dashboards(apps, schema_editor):
    Dashboard = apps.get_model("audit_app", "Dashboard")
    Dashboard.objects.all().update(status="published")


class Migration(migrations.Migration):

    dependencies = [
        ("audit_app", "0008_remove_dashboard_review"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="dashboard",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("published", "Published"),
                    ("rejected", "Rejected"),
                ],
                db_index=True,
                default="draft",
                max_length=20,
                verbose_name="Status",
            ),
        ),
        migrations.AddField(
            model_name="dashboard",
            name="published_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Published at"),
        ),
        migrations.AddField(
            model_name="dashboard",
            name="reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="reviewed_dashboards",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Reviewed by",
            ),
        ),
        migrations.CreateModel(
            name="DashboardRejectionLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("reason", models.TextField(verbose_name="Rejection reason")),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="Created at"),
                ),
                (
                    "dashboard",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rejection_logs",
                        to="audit_app.dashboard",
                        verbose_name="Dashboard",
                    ),
                ),
                (
                    "rejected_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="dashboard_rejection_logs",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Rejected by",
                    ),
                ),
            ],
            options={
                "verbose_name": "Dashboard rejection log",
                "verbose_name_plural": "Dashboard rejection logs",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["dashboard", "created_at"],
                        name="audit_app_d_dashboa_6e8f2a_idx",
                    )
                ],
            },
        ),
        migrations.AlterModelOptions(
            name="dashboard",
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    ("can_upload_files", "Can upload files and create dashboards"),
                    ("can_view_dashboards", "Can view dashboards"),
                    ("can_delete_dashboards", "Can delete dashboards"),
                    ("can_review_dashboards", "Can approve or reject dashboards"),
                ],
                "verbose_name": "Dashboard",
                "verbose_name_plural": "Dashboards",
            },
        ),
        migrations.RunPython(publish_existing_dashboards, migrations.RunPython.noop),
    ]
