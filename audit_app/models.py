from __future__ import annotations

from django.db import models


class UploadSession(models.Model):
    source_name = models.CharField(max_length=255)
    sheet_name = models.CharField(max_length=255, blank=True)
    mode = models.CharField(max_length=32, default="ai")
    locale = models.CharField(max_length=8, default="en")
    content_sha256 = models.CharField(max_length=64, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

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
