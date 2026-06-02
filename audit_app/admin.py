from django.contrib import admin

from .models import CompanyLogo, ObservationRecord, ReportArtifact, UploadSession


@admin.register(UploadSession)
class UploadSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "source_name", "mode", "locale", "uploaded_at")
    search_fields = ("source_name", "sheet_name", "content_sha256")


@admin.register(ObservationRecord)
class ObservationRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "upload_session", "audit_year", "company", "subcompany")
    search_fields = ("audit_year", "observation_name", "company", "subcompany")
    list_filter = ("audit_year", "company", "subcompany")


@admin.register(CompanyLogo)
class CompanyLogoAdmin(admin.ModelAdmin):
    list_display = ("id", "company_key", "subcompany_key", "asset_path")
    search_fields = ("company_key", "subcompany_key")


@admin.register(ReportArtifact)
class ReportArtifactAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "report_id",
        "report_version",
        "rows",
        "columns",
        "created_at",
    )
    search_fields = ("report_id", "report_version")
