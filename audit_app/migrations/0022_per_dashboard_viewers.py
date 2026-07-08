"""Per-dashboard viewer grants; remove workflow templates and company can_view."""
from __future__ import annotations

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def migrate_in_workflow_to_under_review(apps, schema_editor):
    Dashboard = apps.get_model("audit_app", "Dashboard")
    Dashboard.objects.filter(status="in_workflow").update(status="under_review")


class Migration(migrations.Migration):

    dependencies = [
        ("audit_app", "0021_rename_dashboard_template_types"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DashboardViewer",
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
                (
                    "granted_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="Granted at"),
                ),
                (
                    "dashboard",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="viewers",
                        to="audit_app.dashboard",
                        verbose_name="Dashboard",
                    ),
                ),
                (
                    "granted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="dashboard_viewer_grants_given",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Granted by",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dashboard_viewer_grants",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="User",
                    ),
                ),
            ],
            options={
                "verbose_name": "Dashboard viewer",
                "verbose_name_plural": "Dashboard viewers",
                "ordering": ["dashboard_id", "user__username"],
                "unique_together": {("dashboard", "user")},
            },
        ),
        migrations.AddIndex(
            model_name="dashboardviewer",
            index=models.Index(
                fields=["user", "dashboard"],
                name="audit_app_d_user_id_6f0a2d_idx",
            ),
        ),
        migrations.AddField(
            model_name="companymembership",
            name="can_assign_dashboard_viewers",
            field=models.BooleanField(
                default=False,
                help_text="Assign or remove which company members can view each published dashboard.",
                verbose_name="Can assign dashboard viewers",
            ),
        ),
        migrations.RunPython(
            migrate_in_workflow_to_under_review,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name="companymembership",
            name="can_view",
        ),
        migrations.DeleteModel(
            name="DashboardWorkflowStepLog",
        ),
        migrations.DeleteModel(
            name="DashboardWorkflowStepSnapshot",
        ),
        migrations.DeleteModel(
            name="DashboardWorkflowInstance",
        ),
        migrations.DeleteModel(
            name="WorkflowTemplateStep",
        ),
        migrations.DeleteModel(
            name="WorkflowTemplate",
        ),
        migrations.AlterField(
            model_name="dashboard",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("under_review", "Under review"),
                    ("published", "Published"),
                    ("rejected", "Rejected"),
                ],
                db_index=True,
                default="draft",
                max_length=20,
                verbose_name="Status",
            ),
        ),
    ]
