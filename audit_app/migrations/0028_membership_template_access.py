"""Per-template company membership permissions."""

from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion


PERM_FIELDS = (
    "can_upload",
    "can_assign_dashboard_viewers",
    "can_view_own_only",
    "can_review",
    "can_delete_drafts",
)


def _seed_template_access(apps, schema_editor):
    """Preserve existing membership flags on Internal Audit Dashboard only."""
    CompanyMembership = apps.get_model("audit_app", "CompanyMembership")
    CompanyMembershipTemplateAccess = apps.get_model(
        "audit_app", "CompanyMembershipTemplateAccess"
    )
    DashboardTemplateType = apps.get_model("audit_app", "DashboardTemplateType")

    legacy_code = "IAD"
    codes = list(
        DashboardTemplateType.objects.filter(is_deleted=False)
        .order_by("sort_order", "code")
        .values_list("code", flat=True)
    )
    if not codes:
        codes = [legacy_code, "CD"]
    if legacy_code not in codes:
        codes = [legacy_code, *codes]

    rows = []
    existing = set(
        CompanyMembershipTemplateAccess.objects.values_list(
            "membership_id", "template_code"
        )
    )
    denied = {field: False for field in PERM_FIELDS}
    for membership in CompanyMembership.objects.iterator():
        inherited = {field: bool(getattr(membership, field)) for field in PERM_FIELDS}
        for code in codes:
            if (membership.pk, code) in existing:
                continue
            flags = inherited if code == legacy_code else denied
            rows.append(
                CompanyMembershipTemplateAccess(
                    membership=membership,
                    template_code=code,
                    **flags,
                )
            )
        if len(rows) >= 200:
            CompanyMembershipTemplateAccess.objects.bulk_create(rows)
            rows = []
    if rows:
        CompanyMembershipTemplateAccess.objects.bulk_create(rows)


def _unseed_template_access(apps, schema_editor):
    CompanyMembershipTemplateAccess = apps.get_model(
        "audit_app", "CompanyMembershipTemplateAccess"
    )
    CompanyMembershipTemplateAccess.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("audit_app", "0027_dashboardviewer_allowed_attachment_kinds"),
    ]

    operations = [
        migrations.CreateModel(
            name="CompanyMembershipTemplateAccess",
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
                    "template_code",
                    models.SlugField(max_length=32, verbose_name="Template type"),
                ),
                (
                    "can_upload",
                    models.BooleanField(
                        default=False,
                        verbose_name="Can upload files and create dashboards",
                    ),
                ),
                (
                    "can_assign_dashboard_viewers",
                    models.BooleanField(
                        default=False,
                        verbose_name="Can assign dashboard viewers",
                    ),
                ),
                (
                    "can_view_own_only",
                    models.BooleanField(
                        default=False,
                        verbose_name="Can view own dashboards only",
                    ),
                ),
                (
                    "can_review",
                    models.BooleanField(
                        default=False,
                        verbose_name="Can approve or reject dashboards",
                    ),
                ),
                (
                    "can_delete_drafts",
                    models.BooleanField(
                        default=False,
                        verbose_name="Can delete draft dashboards",
                    ),
                ),
                (
                    "membership",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="template_accesses",
                        to="audit_app.companymembership",
                        verbose_name="Membership",
                    ),
                ),
            ],
            options={
                "verbose_name": "Template access",
                "verbose_name_plural": "Template access",
                "ordering": ["template_code"],
                "unique_together": {("membership", "template_code")},
            },
        ),
        migrations.RunPython(_seed_template_access, _unseed_template_access),
    ]
