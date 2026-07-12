"""Add ACC Aproved MoM optional attachment kind for Internal Audit Dashboard."""
from __future__ import annotations

from django.db import migrations, models


NEW_KIND = "accApprovedMoM"

ATTACHMENT_KIND_CHOICES = [
    ("deck", "Company wise Audit committee report"),
    ("highRisk", "High Risk Observations & Emerging Risks"),
    ("tgaViolations", "TGA Violations Report"),
    ("missingVehicle", "Missing Vehicle Report"),
    ("internalAuditQuarterly", "Internal Audit Quarterly Report"),
    ("specialAssignment", "Special Assignment Report"),
    (NEW_KIND, "ACC Aproved MoM"),
]


def seed_acc_approved_mom_settings(apps, schema_editor):
    Company = apps.get_model("audit_app", "Company")
    CompanyAttachmentSetting = apps.get_model("audit_app", "CompanyAttachmentSetting")
    for company in Company.objects.filter(company_kind="main"):
        CompanyAttachmentSetting.objects.get_or_create(
            company=company,
            attachment_kind=NEW_KIND,
            defaults={"is_enabled": True},
        )


class Migration(migrations.Migration):

    dependencies = [
        ("audit_app", "0023_dashboard_user_edits"),
    ]

    operations = [
        migrations.AlterField(
            model_name="companyattachmentsetting",
            name="attachment_kind",
            field=models.CharField(
                choices=ATTACHMENT_KIND_CHOICES,
                max_length=32,
                verbose_name="Attachment type",
            ),
        ),
        migrations.RunPython(seed_acc_approved_mom_settings, migrations.RunPython.noop),
    ]
