import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="CompanyLogo",
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
                ("company_key", models.CharField(max_length=255)),
                ("subcompany_key", models.CharField(blank=True, max_length=255)),
                ("asset_path", models.CharField(max_length=512)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"unique_together": {("company_key", "subcompany_key")}},
        ),
        migrations.CreateModel(
            name="UploadSession",
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
                ("source_name", models.CharField(max_length=255)),
                ("sheet_name", models.CharField(blank=True, max_length=255)),
                ("mode", models.CharField(default="ai", max_length=32)),
                ("locale", models.CharField(default="en", max_length=8)),
                ("content_sha256", models.CharField(blank=True, max_length=64)),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="ReportArtifact",
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
                ("report_id", models.CharField(max_length=64, unique=True)),
                ("report_version", models.CharField(max_length=64)),
                ("rows", models.PositiveIntegerField(default=0)),
                ("columns", models.PositiveIntegerField(default=0)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "upload_session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="artifacts",
                        to="audit_app.uploadsession",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ObservationRecord",
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
                ("audit_year", models.CharField(blank=True, max_length=64)),
                ("observation_name", models.TextField(blank=True)),
                ("department", models.CharField(blank=True, max_length=255)),
                ("ia_status", models.CharField(blank=True, max_length=128)),
                ("company", models.CharField(blank=True, max_length=255)),
                ("subcompany", models.CharField(blank=True, max_length=255)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("raw_row", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "upload_session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="observations",
                        to="audit_app.uploadsession",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="observationrecord",
            index=models.Index(
                fields=["audit_year"], name="audit_app_o_audit_y_3888de_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="observationrecord",
            index=models.Index(
                fields=["company", "subcompany"], name="audit_app_o_company_eb9f4a_idx"
            ),
        ),
    ]
