"""Bilingual admin credentials email (username + temporary password)."""
from __future__ import annotations

from accounts_app.services.email_branding import (
    TEXT_MUTED,
    bilingual_footer_plain,
    build_branded_email_html,
    render_bilingual_block,
    render_bilingual_plain,
)


def build_credentials_email_content(
    *,
    username: str,
    password: str,
    login_url: str,
    logo_url: str | None = None,
) -> dict[str, str]:
    """Return subject, plain, and HTML for a new/reset password email."""
    subject = "بيانات الدخول Login Credentials"

    text_ar = (
        "<p style='margin:0 0 10px;'>السلام عليكم،</p>"
        "<p style='margin:0 0 16px;'>تم إنشاء/تحديث حسابك. استخدم البيانات أدناه لتسجيل الدخول. "
        "سيُطلب منك تغيير كلمة المرور عند أول دخول.</p>"
        f"<p style='margin:0 0 8px;'><strong>اسم المستخدم:</strong> {username}</p>"
        f"<p style='margin:0 0 16px;'><strong>كلمة المرور:</strong> {password}</p>"
        f"<p style='margin:0 0 8px;'><a href='{login_url}'>{login_url}</a></p>"
        f"<p style='margin:0;color:{TEXT_MUTED};'>لا تشارك كلمة المرور مع أي شخص.</p>"
    )
    text_en = (
        "<p style='margin:0 0 10px;'>Hello,</p>"
        "<p style='margin:0 0 16px;'>Your account was created or updated. "
        "Use the credentials below to sign in. You must change your password on first login.</p>"
        f"<p style='margin:0 0 8px;'><strong>Username:</strong> {username}</p>"
        f"<p style='margin:0 0 16px;'><strong>Password:</strong> {password}</p>"
        f"<p style='margin:0 0 8px;'><a href='{login_url}'>{login_url}</a></p>"
        f"<p style='margin:0;color:{TEXT_MUTED};'>Do not share your password with anyone.</p>"
    )

    body_html = render_bilingual_block(text_ar=text_ar, text_en=text_en)
    plain_ar = (
        f"السلام عليكم،\n\nاسم المستخدم: {username}\nكلمة المرور: {password}\n"
        f"رابط الدخول: {login_url}\n\nيُرجى تغيير كلمة المرور عند أول دخول.\n"
    )
    plain_en = (
        f"Hello,\n\nUsername: {username}\nPassword: {password}\n"
        f"Sign in: {login_url}\n\nPlease change your password on first login.\n"
    )
    plain = (
        render_bilingual_plain(text_ar=plain_ar, text_en=plain_en)
        + "\n\n"
        + bilingual_footer_plain()
    )
    html = build_branded_email_html(
        header_ar="بيانات الدخول",
        header_en="Login Credentials",
        body_html=body_html,
        logo_url=logo_url,
    )
    return {"subject": subject, "plain": plain, "html": html}


def send_credentials_email_smtp(
    cfg: dict,
    *,
    to_addr: str,
    username: str,
    password: str,
    login_url: str,
    logo_url: str | None = None,
) -> None:
    from accounts_app.services.email_branding import send_branded_email_smtp

    content = build_credentials_email_content(
        username=username,
        password=password,
        login_url=login_url,
        logo_url=logo_url,
    )
    send_branded_email_smtp(
        cfg,
        to_addr=to_addr.strip(),
        subject=content["subject"],
        plain=content["plain"],
        html=content["html"],
    )
