"""Bilingual OTP email content using shared branding."""
from __future__ import annotations

from accounts_app.services.email_branding import (
    COMPANY_NAME_AR,
    TEXT_MUTED,
    bilingual_footer_plain,
    build_branded_email_html,
    render_bilingual_block,
    render_bilingual_plain,
    render_otp_code,
)
from accounts_app.services.two_factor import OTP_TTL_SECONDS


def otp_validity_minutes() -> int:
    return max(1, OTP_TTL_SECONDS // 60)


def build_otp_email_content(
    *,
    code: str,
    locale: str = "ar",
    logo_url: str | None = None,
) -> dict[str, str]:
    """Return subject, plain text body, and HTML body (always bilingual)."""
    del locale  # backward compatibility; content is always bilingual
    minutes = otp_validity_minutes()

    subject = f"رمز التحقق — Your OTP Code — {COMPANY_NAME_AR}"

    text_ar = (
        "<p style='margin:0 0 10px;'>السلام عليكم،</p>"
        "<p style='margin:0 0 16px;'>يُرجى استخدام رمز التحقق (OTP) المُرفق أدناه لإتمام عملية التحقق من هويتك.</p>"
        f"<p style='margin:16px 0 10px;'>هذا الرمز صالح لمدة <strong>{minutes} دقائق</strong>. "
        "يرجى عدم مشاركة هذا الرمز مع أي شخص.</p>"
        f"<p style='margin:0;color:{TEXT_MUTED};'>"
        "إذا لم تطلب هذا الرمز، يرجى تجاهل هذه الرسالة.<br>"
        "شكراً لاستخدامكم خدماتنا!</p>"
    )
    text_en = (
        "<p style='margin:0 0 10px;'>Hello,</p>"
        "<p style='margin:0 0 16px;'>Please use the (OTP) provided below to complete your identity verification process.</p>"
        f"<p style='margin:16px 0 10px;'>This OTP is valid for <strong>{minutes} minutes</strong>. "
        "Please do not share this code with anyone.</p>"
        f"<p style='margin:0;color:{TEXT_MUTED};'>"
        "If you didn't request this code, please ignore this email.<br>"
        "Thank you for using our service!</p>"
    )

    body_html = (
        render_bilingual_block(text_ar=text_ar, text_en=text_en)
        + f'<div style="margin:0 0 20px;">{render_otp_code(code)}</div>'
    )

    plain_ar = (
        f"السلام عليكم،\n\nرمز التحقق: {code}\n\n"
        f"صالح لمدة {minutes} دقائق. لا تشارك هذا الرمز.\n"
    )
    plain_en = (
        f"Hello,\n\nYour verification code: {code}\n\n"
        f"Valid for {minutes} minutes. Do not share this code.\n"
    )
    plain = (
        render_bilingual_plain(text_ar=plain_ar, text_en=plain_en)
        + "\n\n"
        + bilingual_footer_plain()
    )

    html = build_branded_email_html(
        header_ar="رمز التحقق (OTP)",
        header_en="Your OTP Code",
        body_html=body_html,
        logo_url=logo_url,
    )

    return {"subject": subject, "plain": plain, "html": html}
