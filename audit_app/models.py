"""Dashboard, Company, UploadSession, and audit observation persistence models."""
from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .dashboard_template_codes import (
    DEFAULT_DASHBOARD_TEMPLATE_CODE,
    TEMPLATE_TYPE_SEEDS,
)

COMPANY_KIND_MAIN = "main"
COMPANY_KIND_SUBSIDIARY = "subsidiary"
COMPANY_KIND_CHOICES = [
    (COMPANY_KIND_MAIN, _("Main company")),
    (COMPANY_KIND_SUBSIDIARY, _("Subsidiary")),
]


ATTACHMENT_KIND_CHOICES = [
    ("deck", _("Company wise Audit committee report")),
    ("highRisk", _("High Risk Observations & Emerging Risks")),
    ("tgaViolations", _("TGA Violations Report")),
    ("missingVehicle", _("Missing Vehicle Report")),
    ("internalAuditQuarterly", _("Internal Audit Quarterly Report")),
    ("specialAssignment", _("Special Assignment Report")),
]

ATTACHMENT_KIND_CODES = [code for code, _ in ATTACHMENT_KIND_CHOICES]


class AdminSoftDeleteFields(models.Model):
    """Shared admin soft-delete columns (record hidden, not destroyed)."""

    is_deleted = models.BooleanField(
        default=False,
        verbose_name=_("Soft deleted"),
        db_index=True,
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Deleted at"),
    )
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Deleted by"),
    )

    class Meta:
        abstract = True

    sync_is_active_with_soft_delete = False

    def save(self, *args, **kwargs):
        if self.sync_is_active_with_soft_delete and self.is_deleted and hasattr(
            self, "is_active"
        ):
            self.is_active = False
        super().save(*args, **kwargs)


class Company(AdminSoftDeleteFields):
    """Tenant organization — dashboards and permissions are scoped per company."""

    sync_is_active_with_soft_delete = True

    code = models.SlugField(
        max_length=32,
        unique=True,
        verbose_name=_("Company code"),
        help_text=_("Short identifier, e.g. BTC, NAT"),
    )
    name = models.CharField(max_length=255, verbose_name=_("Display name"))
    excel_company_names = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Excel company names"),
        help_text=_(
            "Names accepted in the Excel Company column for this tenant "
            "(defaults to the company code if empty)."
        ),
    )
    company_kind = models.CharField(
        max_length=16,
        choices=COMPANY_KIND_CHOICES,
        default=COMPANY_KIND_MAIN,
        verbose_name=_("Company type"),
        help_text=_(
            "Main companies have their own dashboards and Excel uploads. "
            "Subsidiaries are registered only for Excel subcompany codes and logos."
        ),
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="subsidiaries",
        verbose_name=_("Parent company"),
        help_text=_("Required when the company type is Subsidiary."),
    )
    logo = models.ImageField(
        upload_to="company_logos/%Y/%m/",
        blank=True,
        verbose_name=_("Company logo"),
        help_text=_("PNG, JPEG, or WebP. Required for all companies."),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    use_workflow_v2 = models.BooleanField(
        default=True,
        verbose_name=_("Use multi-step workflow"),
        help_text=_(
            "When enabled, uploads stay as private drafts until submit; "
            "approval starts a configurable acknowledgment chain before publish."
        ),
    )
    notify_creator_on_publish = models.BooleanField(
        default=True,
        verbose_name=_("Email creator when dashboard is published"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created at"))

    class Meta:
        verbose_name = _("Company")
        verbose_name_plural = _("Companies")
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

    @property
    def is_main(self) -> bool:
        return self.company_kind == COMPANY_KIND_MAIN

    @property
    def is_subsidiary(self) -> bool:
        return self.company_kind == COMPANY_KIND_SUBSIDIARY

    def tenant_root(self) -> "Company":
        current = self
        seen: set[int] = set()
        while current.parent_id is not None:
            if current.pk in seen:
                break
            seen.add(current.pk)
            current = current.parent
        return current

    def accepted_excel_names(self) -> list[str]:
        names = [str(n).strip() for n in (self.excel_company_names or []) if str(n).strip()]
        if not names:
            names = [self.code]
        return names

    def matches_excel_company(self, excel_name: str) -> bool:
        return self.matches_excel_token(excel_name)

    def matches_excel_token(self, excel_name: str) -> bool:
        token = str(excel_name or "").strip()
        if not token:
            return False
        normalized = token.casefold()
        if self.code.casefold() == normalized:
            return True
        if self.name.casefold() == normalized:
            return True
        return any(n.casefold() == normalized for n in self.accepted_excel_names())

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.is_subsidiary:
            if self.parent_id is None:
                errors["parent"] = _("Select the parent main company for a subsidiary.")
            elif self.parent_id == self.pk:
                errors["parent"] = _("A company cannot be its own parent.")
            elif self.parent and not self.parent.is_main:
                errors["parent"] = _("Parent must be a main company.")
        else:
            if self.parent_id is not None:
                errors["parent"] = _("Main companies cannot have a parent.")
        if self.parent_id and self.pk:
            ancestor = self.parent
            seen: set[int] = {self.pk}
            while ancestor is not None:
                if ancestor.pk in seen:
                    errors["parent"] = _("Circular parent chain is not allowed.")
                    break
                seen.add(ancestor.pk)
                ancestor = ancestor.parent
        if errors:
            raise ValidationError(errors)

    def ensure_attachment_settings(self) -> None:
        if self.is_subsidiary:
            return
        existing = set(
            self.attachment_settings.values_list("attachment_kind", flat=True)
        )
        for kind in ATTACHMENT_KIND_CODES:
            if kind not in existing:
                CompanyAttachmentSetting.objects.create(
                    company=self,
                    attachment_kind=kind,
                    is_enabled=True,
                )


class CompanyMembership(AdminSoftDeleteFields):
    """User access and permissions within a single company."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="company_memberships",
        verbose_name=_("User"),
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("Company"),
    )
    can_upload = models.BooleanField(
        default=False,
        verbose_name=_("Can upload files and create dashboards"),
    )
    can_assign_dashboard_viewers = models.BooleanField(
        default=False,
        verbose_name=_("Can assign dashboard viewers"),
        help_text=_(
            "Assign or remove which company members can view each published dashboard."
        ),
    )
    can_view_own_only = models.BooleanField(
        default=False,
        verbose_name=_("Can view own dashboards only"),
        help_text=_(
            "View only dashboards this user created in this company "
            "(draft, rejected, or published)."
        ),
    )
    can_review = models.BooleanField(
        default=False,
        verbose_name=_("Can approve or reject dashboards"),
    )
    can_delete_drafts = models.BooleanField(
        default=False,
        verbose_name=_("Can delete draft dashboards"),
        help_text=_(
            "Remove draft dashboards in this company only. "
            "Published dashboards cannot be deleted."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created at"))

    class Meta:
        verbose_name = _("Company membership")
        verbose_name_plural = _("Company memberships")
        unique_together = ("user", "company")
        ordering = ["company__code", "user__username"]

    def __str__(self) -> str:
        return f"{self.user} @ {self.company.code}"


class CompanyAttachmentSetting(models.Model):
    """Enable or disable optional upload attachments per company."""

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="attachment_settings",
        verbose_name=_("Company"),
    )
    attachment_kind = models.CharField(
        max_length=32,
        choices=ATTACHMENT_KIND_CHOICES,
        verbose_name=_("Attachment type"),
    )
    is_enabled = models.BooleanField(default=True, verbose_name=_("Enabled"))

    class Meta:
        verbose_name = _("Company attachment setting")
        verbose_name_plural = _("Company attachment settings")
        unique_together = ("company", "attachment_kind")
        ordering = ["company__code", "attachment_kind"]

    def __str__(self) -> str:
        state = _("enabled") if self.is_enabled else _("disabled")
        return f"{self.company.code} — {self.attachment_kind} ({state})"


class UploadSession(AdminSoftDeleteFields):
    source_name = models.CharField(max_length=255, verbose_name=_("Source name"))
    sheet_name = models.CharField(max_length=255, blank=True, verbose_name=_("Sheet name"))
    mode = models.CharField(
        max_length=32,
        default=DEFAULT_DASHBOARD_TEMPLATE_CODE,
        verbose_name=_("Mode"),
    )
    locale = models.CharField(max_length=8, default="ar", verbose_name=_("Locale"))
    content_sha256 = models.CharField(max_length=64, blank=True, verbose_name=_("Content hash"))
    raw_data_json = models.TextField(
        blank=True, default="", verbose_name=_("Raw file data (JSON)")
    )
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Uploaded at"))

    class Meta:
        verbose_name = _("Upload session")
        verbose_name_plural = _("Upload sessions")

    def __str__(self) -> str:
        return f"{self.source_name} ({self.uploaded_at:%Y-%m-%d %H:%M})"


class ObservationRecord(AdminSoftDeleteFields):
    upload_session = models.ForeignKey(
        UploadSession,
        on_delete=models.CASCADE,
        related_name="observations",
        verbose_name=_("Upload session"),
    )
    audit_year = models.CharField(max_length=64, blank=True, verbose_name=_("Audit year"))
    observation_name = models.TextField(blank=True, verbose_name=_("Observation name"))
    department = models.CharField(max_length=255, blank=True, verbose_name=_("Department"))
    ia_status = models.CharField(max_length=128, blank=True, verbose_name=_("IA status"))
    company = models.CharField(max_length=255, blank=True, verbose_name=_("Company"))
    subcompany = models.CharField(max_length=255, blank=True, verbose_name=_("Subcompany"))
    email = models.EmailField(blank=True, verbose_name=_("Email"))
    raw_row = models.JSONField(default=dict, blank=True, verbose_name=_("Raw row"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created at"))

    class Meta:
        verbose_name = _("Audit observation")
        verbose_name_plural = _("Audit observations")
        indexes = [
            models.Index(fields=["audit_year"]),
            models.Index(fields=["company", "subcompany"]),
        ]


class CompanyLogo(models.Model):
    company_key = models.CharField(max_length=255)
    subcompany_key = models.CharField(max_length=255, blank=True)
    asset_path = models.CharField(max_length=512)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("company_key", "subcompany_key")
        verbose_name = _("Company logo")
        verbose_name_plural = _("Company logos")


class ReportArtifact(AdminSoftDeleteFields):
    upload_session = models.ForeignKey(
        UploadSession,
        on_delete=models.CASCADE,
        related_name="artifacts",
        verbose_name=_("Upload session"),
    )
    report_id = models.CharField(max_length=64, unique=True, verbose_name=_("Report ID"))
    report_version = models.CharField(max_length=64, verbose_name=_("Report version"))
    rows = models.PositiveIntegerField(default=0, verbose_name=_("Rows"))
    columns = models.PositiveIntegerField(default=0, verbose_name=_("Columns"))
    payload = models.JSONField(default=dict, blank=True, verbose_name=_("Payload"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created at"))

    class Meta:
        verbose_name = _("Report artifact")
        verbose_name_plural = _("Report artifacts")


class DashboardTemplateType(AdminSoftDeleteFields):
    """Editable dashboard template types."""

    sync_is_active_with_soft_delete = True

    code = models.SlugField(
        max_length=32,
        unique=True,
        verbose_name=_("Type code"),
        help_text=_("Internal slug without spaces, e.g. IAD"),
    )
    name = models.CharField(
        max_length=128,
        verbose_name=_("Type name"),
        help_text=_("Display name shown to users"),
    )
    description = models.TextField(blank=True, verbose_name=_("Description"))
    icon = models.CharField(
        max_length=64,
        default="bi-grid",
        verbose_name=_("Bootstrap icon"),
        help_text=_("Example: bi-bar-chart-line-fill"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name=_("Sort order"))

    class Meta:
        verbose_name = _("Dashboard template type")
        verbose_name_plural = _("Dashboard template types")
        ordering = ["sort_order", "code"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


ICON_CHOICES = [
    ("bi-bar-chart-line-fill", _("Bar chart")),
    ("bi-pie-chart-fill", _("Pie chart")),
    ("bi-graph-up-arrow", _("Line / growth chart")),
    ("bi-table", _("Data table")),
    ("bi-clipboard2-data-fill", _("Data analysis")),
    ("bi-file-earmark-spreadsheet-fill", _("Spreadsheet")),
    ("bi-calculator-fill", _("Finance / accounting")),
    ("bi-building-fill", _("Organization / companies")),
]

TEMPLATE_TYPE_CHOICES = [
    (seed["code"], _(seed["name"])) for seed in TEMPLATE_TYPE_SEEDS
]


class DashboardStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    UNDER_REVIEW = "under_review", _("Under review")
    PUBLISHED = "published", _("Published")
    REJECTED = "rejected", _("Rejected")


class Dashboard(models.Model):
    """A named dashboard backed by Excel data stored in the DB."""

    name = models.CharField(max_length=255, verbose_name=_("Dashboard name"))
    description = models.TextField(blank=True, verbose_name=_("Description"))
    icon = models.CharField(
        max_length=64,
        choices=ICON_CHOICES,
        default="bi-bar-chart-line-fill",
        verbose_name=_("Dashboard icon"),
    )
    template_type = models.CharField(
        max_length=32,
        choices=TEMPLATE_TYPE_CHOICES,
        default=DEFAULT_DASHBOARD_TEMPLATE_CODE,
        verbose_name=_("Template type"),
    )
    report_id = models.CharField(max_length=64, unique=True, verbose_name=_("Report ID"))
    html_file = models.CharField(
        max_length=512, blank=True, default="", verbose_name=_("Cached HTML file")
    )
    source_files = models.JSONField(default=list, blank=True, verbose_name=_("Source files"))
    user_edits_json = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Dashboard user edits (JSON)"),
        help_text=_("Persisted audit plan table, cell colors, and review notes."),
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="dashboards",
        null=True,
        blank=True,
        verbose_name=_("Company"),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dashboards",
        verbose_name=_("Created by"),
    )
    upload_session = models.ForeignKey(
        UploadSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dashboard",
        verbose_name=_("Upload session"),
    )
    status = models.CharField(
        max_length=20,
        choices=DashboardStatus.choices,
        default=DashboardStatus.DRAFT,
        verbose_name=_("Status"),
        db_index=True,
    )
    published_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Published at"),
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_dashboards",
        verbose_name=_("Reviewed by"),
    )
    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Submitted for review at"),
    )
    is_deleted = models.BooleanField(
        default=False,
        verbose_name=_("Soft deleted"),
        db_index=True,
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Deleted at"),
    )
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_dashboards",
        verbose_name=_("Deleted by"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created at"))

    class Meta:
        verbose_name = _("Dashboard")
        verbose_name_plural = _("Dashboards")
        ordering = ["-created_at"]
        permissions = [
            ("can_upload_files", _("Can upload files and create dashboards")),
            ("can_view_dashboards", _("Can view dashboards")),
            ("can_delete_dashboards", _("Can remove and restore dashboards")),
            ("can_review_dashboards", _("Can approve or reject dashboards")),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_published(self) -> bool:
        return self.status == DashboardStatus.PUBLISHED

    def get_template_display_name(self) -> str:
        try:
            return (
                DashboardTemplateType.objects.filter(
                    code=self.template_type,
                    is_deleted=False,
                )
                .values_list("name", flat=True)
                .get()
            )
        except DashboardTemplateType.DoesNotExist:
            return dict(TEMPLATE_TYPE_CHOICES).get(
                self.template_type, self.template_type.upper()
            )


class DashboardRejectionLog(AdminSoftDeleteFields):
    """Audit trail of rejection reasons for a dashboard."""

    dashboard = models.ForeignKey(
        Dashboard,
        on_delete=models.CASCADE,
        related_name="rejection_logs",
        verbose_name=_("Dashboard"),
    )
    reason = models.TextField(verbose_name=_("Rejection reason"))
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dashboard_rejection_logs",
        verbose_name=_("Rejected by"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created at"))

    class Meta:
        verbose_name = _("Dashboard rejection log")
        verbose_name_plural = _("Dashboard rejection logs")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["dashboard", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Rejection #{self.pk} on dashboard {self.dashboard_id}"


class DashboardViewer(models.Model):
    """Per-dashboard viewer grant for published dashboards."""

    dashboard = models.ForeignKey(
        Dashboard,
        on_delete=models.CASCADE,
        related_name="viewers",
        verbose_name=_("Dashboard"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dashboard_viewer_grants",
        verbose_name=_("User"),
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dashboard_viewer_grants_given",
        verbose_name=_("Granted by"),
    )
    granted_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Granted at"))

    class Meta:
        verbose_name = _("Dashboard viewer")
        verbose_name_plural = _("Dashboard viewers")
        unique_together = ("dashboard", "user")
        ordering = ["dashboard_id", "user__username"]
        indexes = [
            models.Index(fields=["user", "dashboard"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} → dashboard {self.dashboard_id}"
