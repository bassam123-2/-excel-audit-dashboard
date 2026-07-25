"""Attachment upload filenames must preserve Arabic and English stems."""
from __future__ import annotations

from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

from reports_app.services.report_generation import (
    _safe_upload_stem,
    _save_uploaded_decks_to_media,
    update_dashboard_review_attachments,
)


@pytest.mark.unit
def test_safe_upload_stem_keeps_arabic_and_english_case():
    assert _safe_upload_stem("تقرير المخاطر العالية.pptx") == "تقرير_المخاطر_العالية"
    assert _safe_upload_stem("Fleet Intelligence ExCo.pptx") == "Fleet_Intelligence_ExCo"
    assert _safe_upload_stem("Report تقرير.pptx") == "Report_تقرير"
    assert _safe_upload_stem("../../../evil.pptx") == "evil"
    assert _safe_upload_stem("???.pptx") == "file"


@pytest.mark.django_db
def test_save_uploaded_decks_preserves_arabic_filename(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    upload = SimpleUploadedFile(
        "تقرير_المخاطر.pptx",
        b"PK\x03\x04fake",
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )

    saved = _save_uploaded_decks_to_media(
        request=None,
        report_id="rid-arabic",
        field_prefix="high_risk_deck",
        file_stem_prefix="high_risk_deck",
        uploads=[upload],
    )
    assert len(saved) == 1
    stored_name = Path(saved[0]).name
    assert "تقرير_المخاطر" in stored_name
    assert stored_name.startswith("high_risk_deck1_")
    assert (tmp_path / saved[0]).is_file()


@pytest.mark.django_db
def test_review_attachments_append_arabic_when_english_exist(tmp_path, settings, btc_company):
    """Server must accept Arabic uploads appended to existing English decks."""
    from django.contrib.auth.models import User

    from audit_app.models import CompanyMembership, Dashboard, DashboardStatus

    settings.MEDIA_ROOT = tmp_path
    btc_company.ensure_attachment_settings()
    user = User.objects.create_user("ar_attach_reviewer", password="Test@1234")
    profile = user.profile
    profile.two_factor_enabled = False
    profile.job_title = "Reviewer"
    profile.save(update_fields=["two_factor_enabled", "job_title"])
    CompanyMembership.objects.create(
        user=user, company=btc_company, can_review=True, can_upload=True
    )

    report_id = "rid-ar-append"
    media_dir = tmp_path / "decks" / report_id
    media_dir.mkdir(parents=True)
    existing_rel = f"decks/{report_id}/deck1_english.pptx"
    (tmp_path / existing_rel).write_bytes(b"PK\x03\x04old")

    dashboard = Dashboard.objects.create(
        name="AR attach",
        report_id=report_id,
        company=btc_company,
        created_by=user,
        status=DashboardStatus.UNDER_REVIEW,
        template_type="IAD",
        source_files={"excel": ["x.xlsx"], "decks": [existing_rel]},
    )

    arabic = SimpleUploadedFile(
        "تقرير_اللجنة.pptx",
        b"PK\x03\x04arabic",
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
    factory = RequestFactory()
    request = factory.post("/review-attachments/", data={})
    request.FILES.setlist("deck", [arabic])
    request.session = {"ui_lang": "en"}

    update_dashboard_review_attachments(request, dashboard, company=btc_company)
    dashboard.refresh_from_db()
    decks = dashboard.source_files.get("decks") or []
    assert len(decks) == 2
    assert existing_rel in decks
    assert any("تقرير_اللجنة" in Path(p).name for p in decks)
    assert all((tmp_path / p).is_file() for p in decks)
