from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


ATTACHMENT_KIND_CHOICES = [
    ("deck", _("Company wise Audit committee report")),
    ("highRisk", _("High Risk Observations & Emerging Risks")),
    ("tgaViolations", _("TGA Violations Report")),
    ("missingVehicle", _("Missing Vehicle Report")),
    ("internalAuditQuarterly", _("Internal Audit Quarterly Report")),
    ("specialAssignment", _("Special Assignment Report")),
]

ATTACHMENT_KIND_CODES = [code for code, _ in ATTACHMENT_KIND_CHOICES]


class Company(models.Model):
    """Tenant organization — dashboards and permissions are scoped per company."""

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
    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created at"))

    class Meta:
        verbose_name = _("Company")
        verbose_name_plural = _("Companies")
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

    def accepted_excel_names(self) -> list[str]:
        names = [str(n).strip() for n in (self.excel_company_names or []) if str(n).strip()]
        if not names:
            names = [self.code]
        return names

    def matches_excel_company(self, excel_name: str) -> bool:
        token = str(excel_name or "").strip()
        if not token:
            return False
        normalized = token.casefold()
        return any(n.casefold() == normalized for n in self.accepted_excel_names())

    def ensure_attachment_settings(self) -> None:
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


class CompanyMembership(models.Model):
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
    can_view = models.BooleanField(
        default=False,
        verbose_name=_("Can view dashboards"),
        help_text=_("View all published dashboards in this company."),
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


class UploadSession(models.Model):
    source_name = models.CharField(max_length=255)
    sheet_name = models.CharField(max_length=255, blank=True)
    mode = models.CharField(max_length=32, default="ai")
    locale = models.CharField(max_length=8, default="ar")
    content_sha256 = models.CharField(max_length=64, blank=True)
    raw_data_json = models.TextField(
        blank=True, default="", verbose_name=_("Raw file data (JSON)")
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Upload session")
        verbose_name_plural = _("Upload sessions")

    def __str__(self) -> str:
        return f"{self.source_name} ({self.uploaded_at:%Y-%m-%d %H:%M})"


class ObservationRecord(models.Model):
    upload_session = models.ForeignKey(
        UploadSession, on_delete=models.CASCADE, related_name="observations"
    )
    audit_year = models.CharField(max_length=64, blank=True)
    observation_name = models.TextField(blank=True)
    department = models.CharField(max_length=255, blank=True)
    ia_status = models.CharField(max_length=128, blank=True)
    company = models.CharField(max_length=255, blank=True)
    subcompany = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    raw_row = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

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


class ReportArtifact(models.Model):
    upload_session = models.ForeignKey(
        UploadSession, on_delete=models.CASCADE, related_name="artifacts"
    )
    report_id = models.CharField(max_length=64, unique=True)
    report_version = models.CharField(max_length=64)
    rows = models.PositiveIntegerField(default=0)
    columns = models.PositiveIntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Report artifact")
        verbose_name_plural = _("Report artifacts")


class DashboardTemplateType(models.Model):
    """Editable dashboard template types."""

    code = models.SlugField(
        max_length=32,
        unique=True,
        verbose_name=_("Type code"),
        help_text=_("Internal slug without spaces, e.g. ai"),
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
    ("ai", _("AI analytical dashboard")),
]


class DashboardStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
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
        default="ai",
        verbose_name=_("Template type"),
    )
    report_id = models.CharField(max_length=64, unique=True, verbose_name=_("Report ID"))
    html_file = models.CharField(
        max_length=512, blank=True, default="", verbose_name=_("Cached HTML file")
    )
    source_files = models.JSONField(default=list, blank=True, verbose_name=_("Source files"))
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
            return DashboardTemplateType.objects.get(code=self.template_type).name
        except DashboardTemplateType.DoesNotExist:
            return dict(TEMPLATE_TYPE_CHOICES).get(
                self.template_type, self.template_type.upper()
            )


class DashboardRejectionLog(models.Model):
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
