"""Password set token flow (Phase C credentials email)."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import override_settings
from django.urls import reverse

from accounts_app.models import PasswordSetToken
from accounts_app.services.credentials_email import build_credentials_email_content
from accounts_app.services.email_branding import LOGO_CID_REF, require_secure_email_base_url
from accounts_app.services.password_set_token import (
    build_set_password_url,
    create_password_set_token,
    get_valid_token,
    set_password_with_token,
)
from tests.factories import make_user


@pytest.mark.django_db
def test_create_and_consume_password_set_token():
    user = make_user("token_user", email="token_user@example.com")
    raw = create_password_set_token(user)
    token = get_valid_token(raw)
    assert token is not None
    assert token.user_id == user.pk

    set_password_with_token(token=token, new_password="NewComplex1!")
    user.refresh_from_db()
    assert user.check_password("NewComplex1!")
    assert user.profile.must_change_password_on_login is False

    token.refresh_from_db()
    assert token.used_at is not None
    assert get_valid_token(raw) is None


@pytest.mark.django_db
def test_password_set_token_single_use():
    user = make_user("once_user", email="once@example.com")
    raw = create_password_set_token(user)
    token = get_valid_token(raw)
    set_password_with_token(token=token, new_password="NewComplex1!")
    assert get_valid_token(raw) is None


@pytest.mark.django_db
def test_create_password_set_token_invalidates_previous():
    user = make_user("replace_user", email="replace@example.com")
    first = create_password_set_token(user)
    second = create_password_set_token(user)
    assert get_valid_token(first) is None
    assert get_valid_token(second) is not None
    assert PasswordSetToken.objects.filter(user=user, used_at__isnull=True).count() == 1


@pytest.mark.unit
def test_credentials_email_contains_set_password_link_not_password():
    content = build_credentials_email_content(
        username="newuser",
        set_password_url="https://dash-audit.alissa-ia.com/set-password/abc123/",
    )
    joined = content["plain"] + content["html"]
    assert "newuser" in joined
    assert "newuser" in content["subject"]
    assert "https://dash-audit.alissa-ia.com/set-password/abc123/" in joined
    assert "ComplexPass1!" not in joined
    assert "Set Password" in content["html"]
    assert "اسم المستخدم" in content["html"]
    assert "Username</p>" in content["html"]


@pytest.mark.unit
def test_credentials_email_escapes_html_special_chars():
    content = build_credentials_email_content(
        username="user<test>",
        set_password_url="https://example.com/set-password/x?a=1&b=2",
    )
    html = content["html"]
    assert "user&lt;test&gt;" in html
    assert "user<test>" not in html
    assert "https://example.com/set-password/x?a=1&amp;b=2" in html
    assert content["subject"].startswith("[Audit Dashboard]")


@pytest.mark.django_db
def test_set_password_view_success(client):
    user = make_user("setpw_user", email="setpw@example.com")
    raw = create_password_set_token(user)
    url = reverse("set_password", kwargs={"token": raw})

    response = client.post(
        url,
        {"new_password1": "NewComplex1!", "new_password2": "NewComplex1!"},
    )
    assert response.status_code == 302
    assert response.url.endswith(reverse("login"))
    user.refresh_from_db()
    assert user.check_password("NewComplex1!")


@pytest.mark.django_db
def test_set_password_view_invalid_token(client):
    url = reverse("set_password", kwargs={"token": "not-a-valid-token"})
    response = client.get(url)
    assert response.status_code == 200
    assert b"invalid" in response.content.lower() or "غير صالح" in response.content.decode()


@pytest.mark.unit
def test_build_set_password_url_uses_public_site_url(monkeypatch):
    monkeypatch.setenv("PUBLIC_SITE_URL", "https://dash-audit.alissa-ia.com")
    url = build_set_password_url("abc", base_url="http://internal.local/")
    assert url.startswith("https://dash-audit.alissa-ia.com/set-password/")


@pytest.mark.unit
@override_settings(DEBUG=False)
def test_require_secure_email_base_url_rejects_http_without_public_site(monkeypatch):
    monkeypatch.delenv("PUBLIC_SITE_URL", raising=False)
    with pytest.raises(ValueError, match="insecure_email_base_url"):
        require_secure_email_base_url("http://dash-audit.alissa-ia.com")


@pytest.mark.unit
def test_branded_email_uses_inline_logo_cid_when_file_exists(monkeypatch, tmp_path):
    from accounts_app.services import email_branding as branding

    logo_file = tmp_path / "logo.png"
    logo_file.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(branding, "LOGO_PATH", logo_file)

    html = branding.build_branded_email_html(
        header_ar="اختبار",
        header_en="Test",
        body_html="<p>body</p>",
    )
    assert LOGO_CID_REF in html

    captured: dict = {}

    def fake_send(cfg, *, from_addr, to_addr, msg):
        captured["msg"] = msg

    monkeypatch.setattr(branding, "_smtp_send_message", fake_send)
    branding.send_branded_email_smtp(
        {"host": "x", "from": "noreply@example.com"},
        to_addr="user@example.com",
        subject="Test",
        plain="plain",
        html=html,
    )

    payload = captured["msg"].as_string()
    assert "Content-ID: <company_logo>" in payload
    assert "multipart/related" in payload
