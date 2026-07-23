"""Add Internal Audit Detailed Reports optional attachment kind."""
from __future__ import annotations

from django.db import migrations, models


NEW_KIND = "internalAuditDetailed"

ATTACHMENT_KIND_CHOICES = [
    ("deck", "Company wise Audit committee report"),
    ("highRisk", "High Risk Observations & Emerging Risks"),
    ("tgaViolations", "TGA Violations Report"),
    ("missingVehicle", "Missing Vehicle Report"),
    ("internalAuditQuarterly", "Internal Audit Quarterly Report"),
    ("specialAssignment", "Special Assignment Report"),
    ("accApprovedMoM", "ACC Aproved MoM"),
    (NEW_KIND, "Internal Audit Detailed Reports"),
]


def seed_internal_audit_detailed_settings(apps, schema_editor):
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
        ("audit_app", "0024_acc_approved_mom_attachment"),
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
        migrations.RunPython(seed_internal_audit_detailed_settings, migrations.RunPython.noop),
    ]
