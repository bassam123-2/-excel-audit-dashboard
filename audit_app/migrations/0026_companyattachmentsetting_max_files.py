"""Add per-kind max_files limit on company attachment settings."""
from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audit_app", "0025_internal_audit_detailed_attachment"),
    ]

    operations = [
        migrations.AddField(
            model_name="companyattachmentsetting",
            name="max_files",
            field=models.PositiveSmallIntegerField(
                default=4,
                help_text="Maximum number of attachment files allowed for this type.",
                verbose_name="Max files",
            ),
        ),
    ]
