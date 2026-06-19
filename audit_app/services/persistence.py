"""Persist report artifacts and observation rows after Excel analysis."""
from __future__ import annotations

from typing import Any

from django.db import transaction

from audit_app.models import ObservationRecord, ReportArtifact, UploadSession


@transaction.atomic
def persist_report_result(
    *,
    source_name: str,
    sheet_name: str | None,
    locale: str,
    mode: str,
    content_sha256: str,
    observation_rows: list[dict[str, Any]],
    audit_payload: dict[str, Any],
) -> UploadSession:
    """Create UploadSession, ObservationRecord rows, and ReportArtifact for one analysis run."""
    session = UploadSession.objects.create(
        source_name=source_name,
        sheet_name=sheet_name or "",
        locale=locale,
        mode=mode,
        content_sha256=content_sha256,
    )
    for row in observation_rows[:8000]:
        ObservationRecord.objects.create(
            upload_session=session,
            audit_year=str(row.get("y", "")).strip(),
            observation_name=str(row.get("obs", "")).strip(),
            department=str(row.get("d", "")).strip(),
            ia_status=str(row.get("s", "")).strip(),
            company=str(row.get("co", "")).strip(),
            subcompany=str(row.get("sco", "")).strip(),
            email=str(row.get("email", "")).strip(),
            raw_row=row,
        )
    ReportArtifact.objects.create(
        upload_session=session,
        report_id=str(audit_payload.get("report_id", "")),
        report_version=str(audit_payload.get("report_version", "")),
        rows=int(audit_payload.get("rows", 0) or 0),
        columns=int(audit_payload.get("columns", 0) or 0),
        payload=audit_payload or {},
    )
    return session
