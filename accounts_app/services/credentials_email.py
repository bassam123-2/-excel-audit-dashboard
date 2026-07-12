"""Bilingual admin credentials email (username + secure set-password link)."""
from __future__ import annotations

from html import escape

from accounts_app.models import PASSWORD_SET_TOKEN_TTL_HOURS
from accounts_app.services.email_branding import (
    TEXT_MUTED,
    bilingual_footer_plain,
    build_branded_email_html,
    format_bilingual_subject,
    render_bilingual_block,
    render_bilingual_plain,
    render_cta_button,
    render_username_box,
)


def build_credentials_email_content(
    *,
    username: str,
    set_password_url: str,
    logo_url: str | None = None,
) -> dict[str, str]:
    """Return subject, plain, and HTML for a new/reset password email."""
    subject = format_bilingual_subject(
        text_ar=f"تعيين كلمة المرور — {username}",
        text_en=f"Set Your Password — {username}",
    )

    safe_set_password_url = escape(set_password_url, quote=True)
    hours = PASSWORD_SET_TOKEN_TTL_HOURS

    text_ar = (
        "<p style='margin:0 0 10px;'>السلام عليكم،</p>"
        "<p style='margin:0 0 16px;'>تم إنشاء/تحديث حسابك. استخدم اسم المستخدم الظاهر "
        "أدناه ثم اضغط الزر لتعيين كلمة المرور.</p>"
        f"<p style='margin:0 0 8px;color:{TEXT_MUTED};'>"
        f"الرابط صالح لمدة {hours} ساعة ويُستخدم مرة واحدة فقط.</p>"
    )
    text_en = (
        "<p style='margin:0 0 10px;'>Hello,</p>"
        "<p style='margin:0 0 16px;'>Your account was created or updated. "
        "Use the username shown below, then click the button to set your password.</p>"
        f"<p style='margin:0 0 8px;color:{TEXT_MUTED};'>"
        f"This link is valid for {hours} hours and can only be used once.</p>"
    )

    body_html = (
        render_bilingual_block(text_ar=text_ar, text_en=text_en)
        + f'<div style="margin:0 0 20px;">{render_username_box(username)}</div>'
        + render_cta_button(
            set_password_url,
            label_ar="تعيين كلمة المرور",
            label_en="Set Password",
        )
        + f"<p style='margin:16px 0 0;font-size:13px;color:{TEXT_MUTED};'>"
        f"<span dir='rtl'>أو انسخ الرابط:</span> / "
        f"<span dir='ltr'>Or copy this link:</span><br>"
        f'<a href="{safe_set_password_url}">{safe_set_password_url}</a></p>'
    )

    plain_ar = (
        f"السلام عليكم،\n\nاسم المستخدم: {username}\n"
        f"رابط تعيين كلمة المرور: {set_password_url}\n\n"
        f"صالح لمدة {hours} ساعة.\n"
    )
    plain_en = (
        f"Hello,\n\nUsername: {username}\n"
        f"Set password: {set_password_url}\n\n"
        f"Valid for {hours} hours.\n"
    )
    plain = (
        render_bilingual_plain(text_ar=plain_ar, text_en=plain_en)
        + "\n\n"
        + bilingual_footer_plain()
    )
    html = build_branded_email_html(
        header_ar="تعيين كلمة المرور",
        header_en="Set Your Password",
        body_html=body_html,
        logo_url=logo_url,
    )
    return {"subject": subject, "plain": plain, "html": html}


def send_credentials_email_smtp(
    cfg: dict,
    *,
    to_addr: str,
    username: str,
    set_password_url: str,
    logo_url: str | None = None,
) -> None:
    from accounts_app.services.email_branding import send_branded_email_smtp

    content = build_credentials_email_content(
        username=username,
        set_password_url=set_password_url,
        logo_url=logo_url,
    )
    send_branded_email_smtp(
        cfg,
        to_addr=to_addr.strip(),
        subject=content["subject"],
        plain=content["plain"],
        html=content["html"],
    )
