"""Per-viewer attachment kind grants on DashboardViewer."""
from __future__ import annotations

from django.db import migrations, models


def _backfill_existing_viewers(apps, schema_editor):
    """Preserve prior behavior: existing viewers keep all company-enabled kinds."""
    DashboardViewer = apps.get_model("audit_app", "DashboardViewer")
    CompanyAttachmentSetting = apps.get_model("audit_app", "CompanyAttachmentSetting")
    ATTACHMENT_KIND_CODES = [
        "deck",
        "highRisk",
        "tgaViolations",
        "missingVehicle",
        "internalAuditQuarterly",
        "specialAssignment",
        "accApprovedMoM",
        "internalAuditDetailed",
    ]

    enabled_by_company: dict[int, list[str]] = {}
    for company_id, kind in CompanyAttachmentSetting.objects.filter(
        is_enabled=True
    ).values_list("company_id", "attachment_kind"):
        enabled_by_company.setdefault(company_id, []).append(kind)

    to_update = []
    for viewer in DashboardViewer.objects.select_related("dashboard").iterator():
        company_id = viewer.dashboard.company_id
        if company_id is None:
            kinds = list(ATTACHMENT_KIND_CODES)
        else:
            kinds = enabled_by_company.get(company_id) or list(ATTACHMENT_KIND_CODES)
        viewer.allowed_attachment_kinds = kinds
        to_update.append(viewer)
        if len(to_update) >= 200:
            DashboardViewer.objects.bulk_update(
                to_update, ["allowed_attachment_kinds"]
            )
            to_update = []
    if to_update:
        DashboardViewer.objects.bulk_update(to_update, ["allowed_attachment_kinds"])


def _noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("audit_app", "0026_companyattachmentsetting_max_files"),
    ]

    operations = [
        migrations.AddField(
            model_name="dashboardviewer",
            name="allowed_attachment_kinds",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    "Attachment kind codes this viewer may see on this dashboard "
                    "(e.g. deck, highRisk). Empty means no attachments."
                ),
                verbose_name="Allowed attachment kinds",
            ),
        ),
        migrations.RunPython(_backfill_existing_viewers, _noop_reverse),
    ]
