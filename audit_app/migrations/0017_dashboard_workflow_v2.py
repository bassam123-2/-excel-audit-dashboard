# Generated manually for workflow v2

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audit_app", "0016_company_logo_hierarchy"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="notify_creator_on_publish",
            field=models.BooleanField(
                default=True,
                verbose_name="Email creator when dashboard is published",
            ),
        ),
        migrations.AddField(
            model_name="company",
            name="use_workflow_v2",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "When enabled, uploads stay as private drafts until submit; "
                    "approval starts a configurable acknowledgment chain before publish."
                ),
                verbose_name="Use multi-step workflow",
            ),
        ),
        migrations.AddField(
            model_name="dashboard",
            name="submitted_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Submitted for review at",
            ),
        ),
        migrations.AlterField(
            model_name="dashboard",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("under_review", "Under review"),
                    ("in_workflow", "In workflow"),
                    ("published", "Published"),
                    ("rejected", "Rejected"),
                ],
                db_index=True,
                default="draft",
                max_length=20,
                verbose_name="Status",
            ),
        ),
        migrations.CreateModel(
            name="WorkflowTemplate",
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
                ("name", models.CharField(default="Default", max_length=128, verbose_name="Name")),
                ("version", models.PositiveIntegerField(default=1, verbose_name="Version")),
                ("is_active", models.BooleanField(default=True, verbose_name="Active")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Created at")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Updated at")),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workflow_templates",
                        to="audit_app.company",
                        verbose_name="Company",
                    ),
                ),
            ],
            options={
                "verbose_name": "Workflow template",
                "verbose_name_plural": "Workflow templates",
                "ordering": ["company__code", "-version"],
            },
        ),
        migrations.CreateModel(
            name="DashboardWorkflowInstance",
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
                ("template_version", models.PositiveIntegerField(verbose_name="Template version")),
                (
                    "current_step_index",
                    models.PositiveIntegerField(default=0, verbose_name="Current step"),
                ),
                ("total_steps", models.PositiveIntegerField(default=0, verbose_name="Total steps")),
                ("is_complete", models.BooleanField(default=False, verbose_name="Complete")),
                ("started_at", models.DateTimeField(auto_now_add=True, verbose_name="Started at")),
                (
                    "completed_at",
                    models.DateTimeField(blank=True, null=True, verbose_name="Completed at"),
                ),
                (
                    "current_assignee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assigned_workflow_dashboards",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Current assignee",
                    ),
                ),
                (
                    "dashboard",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workflow_instance",
                        to="audit_app.dashboard",
                        verbose_name="Dashboard",
                    ),
                ),
            ],
            options={
                "verbose_name": "Dashboard workflow instance",
                "verbose_name_plural": "Dashboard workflow instances",
            },
        ),
        migrations.CreateModel(
            name="WorkflowTemplateStep",
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
                ("step_order", models.PositiveIntegerField(verbose_name="Step order")),
                (
                    "assignee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workflow_template_steps",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Assignee",
                    ),
                ),
                (
                    "template",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="steps",
                        to="audit_app.workflowtemplate",
                        verbose_name="Template",
                    ),
                ),
            ],
            options={
                "verbose_name": "Workflow template step",
                "verbose_name_plural": "Workflow template steps",
                "ordering": ["template_id", "step_order"],
            },
        ),
        migrations.CreateModel(
            name="DashboardWorkflowStepSnapshot",
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
                ("step_order", models.PositiveIntegerField(verbose_name="Step order")),
                (
                    "assignee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workflow_step_snapshots",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Assignee",
                    ),
                ),
                (
                    "instance",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="step_snapshots",
                        to="audit_app.dashboardworkflowinstance",
                        verbose_name="Workflow instance",
                    ),
                ),
            ],
            options={
                "verbose_name": "Workflow step snapshot",
                "verbose_name_plural": "Workflow step snapshots",
                "ordering": ["instance_id", "step_order"],
            },
        ),
        migrations.CreateModel(
            name="DashboardWorkflowStepLog",
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
                ("step_order", models.PositiveIntegerField(verbose_name="Step order")),
                ("acknowledged_at", models.DateTimeField(auto_now_add=True, verbose_name="Acknowledged at")),
                (
                    "acknowledged_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="workflow_acknowledgments_performed",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Acknowledged by",
                    ),
                ),
                (
                    "assignee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="workflow_acknowledgments",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Assignee",
                    ),
                ),
                (
                    "instance",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="step_logs",
                        to="audit_app.dashboardworkflowinstance",
                        verbose_name="Workflow instance",
                    ),
                ),
            ],
            options={
                "verbose_name": "Workflow step log",
                "verbose_name_plural": "Workflow step logs",
                "ordering": ["-acknowledged_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="workflowtemplate",
            constraint=models.UniqueConstraint(
                fields=("company", "version"),
                name="uniq_workflow_template_company_version",
            ),
        ),
        migrations.AddConstraint(
            model_name="workflowtemplatestep",
            constraint=models.UniqueConstraint(
                fields=("template", "step_order"),
                name="uniq_workflow_template_step_order",
            ),
        ),
        migrations.AddConstraint(
            model_name="dashboardworkflowstepsnapshot",
            constraint=models.UniqueConstraint(
                fields=("instance", "step_order"),
                name="uniq_workflow_instance_step_order",
            ),
        ),
    ]
