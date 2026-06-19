"""Outlook-safe HTML email structure regression tests."""
from __future__ import annotations

import pytest

from accounts_app.services.email_branding import (
    BRAND_BLUE,
    build_branded_email_html,
    render_bilingual_header,
    render_cta_button,
)


@pytest.mark.unit
def test_header_uses_table_rows_not_display_block_spans():
    html = render_bilingual_header(
        header_ar="طلب مراجعة لوحة تحكم",
        header_en="Dashboard Pending Review",
    )
    assert "<table" in html
    assert 'dir="rtl"' in html
    assert 'dir="ltr"' in html
    assert "display:block" not in html


@pytest.mark.unit
def test_cta_button_uses_bulletproof_table_and_vml():
    html = render_cta_button(
        "https://example.com/dashboards/1/",
        label_ar="مراجعة اللوحة",
        label_en="Review Dashboard",
    )
    assert "v:roundrect" in html
    assert "[if mso]" in html
    assert "[if !mso]" in html
    assert "display:inline-block" not in html
    assert BRAND_BLUE in html
    assert "مراجعة اللوحة" in html
    assert "Review Dashboard" in html


@pytest.mark.unit
def test_branded_email_header_and_cta_outlook_safe():
    html = build_branded_email_html(
        header_ar="طلب مراجعة لوحة تحكم",
        header_en="Dashboard Pending Review",
        body_html=render_cta_button(
            "https://example.com/dashboards/1/",
            label_ar="مراجعة اللوحة",
            label_en="Review Dashboard",
        ),
    )
    assert 'xmlns:v="urn:schemas-microsoft-com:vml"' in html
    assert "OfficeDocumentSettings" in html
    body = html.split("<body", 1)[1]
    assert 'style="display:block' not in body
    assert html.count('dir="rtl"') >= 1
    assert html.count('dir="ltr"') >= 1
