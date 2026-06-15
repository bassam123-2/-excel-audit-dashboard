"""OTP HTML email template tests."""
from __future__ import annotations

import pytest

from accounts_app.services.email_branding import BRAND_BLUE, BRAND_RED, resolve_logo_path, resolve_logo_url
from accounts_app.services.otp_email import build_otp_email_content


@pytest.mark.unit
def test_otp_email_bilingual_html_branding():
    logo_url = "https://example.com/static/logos/brand.png"
    content = build_otp_email_content(code="569531", locale="en", logo_url=logo_url)
    html = content["html"]
    assert "Your OTP Code" in html
    assert "رمز التحقق" in html
    assert "569531" in html
    assert BRAND_BLUE in html
    assert BRAND_RED in html
    assert f'src="{logo_url}"' in html
    assert "cid:company_logo" not in html
    assert "Abdullatif Alissa Group Holding Co." in html
    assert 'dir="rtl"' in html
    assert 'dir="ltr"' in html


@pytest.mark.unit
def test_otp_email_bilingual_plain():
    content = build_otp_email_content(code="123456", locale="ar")
    plain = content["plain"]
    assert "123456" in plain
    assert "السلام عليكم" in plain
    assert "Hello" in plain
    assert "شركة مجموعة عبداللطيف العيسى القابضة" in plain


@pytest.mark.unit
def test_otp_email_arabic_locale_still_bilingual():
    content = build_otp_email_content(code="123456", locale="ar")
    html = content["html"]
    assert "123456" in html
    assert "10" in html or "دقائق" in html
    assert "minutes" in html


@pytest.mark.unit
def test_company_logo_file_exists():
    assert resolve_logo_path() is not None


@pytest.mark.unit
def test_resolve_logo_url_from_base_url():
    url = resolve_logo_url(base_url="https://dashboard.example.com/")
    assert url is not None
    assert url.startswith("https://dashboard.example.com/static/logos/")
    assert "Abdullatif" in url
