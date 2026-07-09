"""Shared branded HTML email layout and SMTP sender."""
from __future__ import annotations

import os
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote

BRAND_BLUE = "#004B9B"
BRAND_RED = "#E31E24"
BODY_BG = "#f0f4f8"
CARD_BG = "#ffffff"
CONTENT_BOX_BG = "#f3f4f6"
FOOTER_BG = "#f3f4f6"
TEXT_PRIMARY = "#333333"
TEXT_MUTED = "#666666"
TEXT_FOOTER = "#888888"
DIVIDER_COLOR = "#e2e8f0"

BRAND_NAME_EN = "Audit Dashboard"
BRAND_NAME_AR = "لوحة التدقيق"
BRAND_SUBJECT_PREFIX = "[Audit Dashboard]"
SUBJECT_MAX_LENGTH = 78
LOGO_FILENAME = "Abdullatif Alissa Group Holding Co.png"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGO_PATH = _PROJECT_ROOT / "assets" / "logos" / LOGO_FILENAME
LOGO_STATIC_PATH = f"/static/logos/{quote(LOGO_FILENAME)}"
LOGO_CID = "company_logo"
LOGO_CID_REF = f"cid:{LOGO_CID}"

SMTP_TIMEOUT_SECONDS = 30


def format_bilingual_subject(*, text_ar: str, text_en: str) -> str:
    """Branded subject line: [Audit Dashboard] Arabic | English."""
    body = f"{text_ar} | {text_en}"
    if body.startswith(BRAND_SUBJECT_PREFIX):
        return truncate_email_subject(body)
    return truncate_email_subject(f"{BRAND_SUBJECT_PREFIX} {body}")


def truncate_email_subject(subject: str, *, max_length: int = SUBJECT_MAX_LENGTH) -> str:
    subject = " ".join(str(subject or "").split())
    if len(subject) <= max_length:
        return subject
    if max_length <= 1:
        return subject[:max_length]
    return subject[: max_length - 1].rstrip() + "…"


def resolve_from_name(cfg: dict[str, Any] | None = None) -> str:
    if cfg:
        name = str(cfg.get("from_name") or cfg.get("sender_name") or "").strip()
        if name:
            return name
    return BRAND_NAME_EN


def _message_id_domain(from_addr: str) -> str:
    domain = from_addr.rsplit("@", 1)[-1].strip().lower()
    return domain or "localhost"


def enrich_message_headers(
    msg,
    cfg: dict[str, Any],
    *,
    from_addr: str,
    to_addr: str,
) -> None:
    from email.utils import format_datetime, make_msgid

    from accounts_app.services.project_timezone import project_local_now

    msg["Date"] = format_datetime(project_local_now())
    msg["Message-ID"] = make_msgid(domain=_message_id_domain(from_addr))
    msg["MIME-Version"] = "1.0"
    reply_to = str(cfg.get("reply_to") or "").strip()
    msg["Reply-To"] = reply_to or from_addr
    msg["X-Auto-Response-Suppress"] = "All"
    msg["To"] = to_addr


def _smtp_send_message(
    cfg: dict[str, Any],
    *,
    from_addr: str,
    to_addr: str,
    msg,
) -> None:
    import smtplib
    import ssl

    host = str(cfg.get("host", "")).strip()
    port = int(cfg.get("port", 587))
    use_tls = bool(cfg.get("use_tls", True))
    user = str(cfg.get("username") or cfg.get("user") or from_addr).strip()
    password = str(cfg.get("password", ""))
    timeout = int(cfg.get("timeout", SMTP_TIMEOUT_SECONDS))
    tls_context = ssl.create_default_context()

    with smtplib.SMTP(host, port, timeout=timeout) as smtp:
        smtp.ehlo()
        if use_tls:
            smtp.starttls(context=tls_context)
            smtp.ehlo()
        if user and password:
            smtp.login(user, password)
        smtp.sendmail(from_addr, [to_addr], msg.as_string())


def normalize_email_base_url(base_url: str) -> str:
    """Prefer PUBLIC_SITE_URL (HTTPS) for links embedded in outbound email."""
    site = os.environ.get("PUBLIC_SITE_URL", "").strip().rstrip("/")
    if site:
        return site
    base = str(base_url or "").strip().rstrip("/")
    if base.startswith("http://"):
        try:
            from django.conf import settings

            if not settings.DEBUG:
                base = "https://" + base[len("http://") :]
        except Exception:
            pass
    return base


def require_secure_email_base_url(base_url: str) -> str:
    """Return a HTTPS base URL for email links; raise in production if insecure."""
    site = os.environ.get("PUBLIC_SITE_URL", "").strip().rstrip("/")
    if site:
        if site.startswith("https://"):
            return site
        if site.startswith("http://"):
            _raise_if_production_insecure_url()
            return site
        return site

    base = str(base_url or "").strip().rstrip("/")
    if base.startswith("https://"):
        return base
    if base.startswith("http://"):
        _raise_if_production_insecure_url()
        return base

    _raise_if_production_insecure_url()
    return base


def _raise_if_production_insecure_url() -> None:
    try:
        from django.conf import settings

        if not settings.DEBUG:
            raise ValueError("insecure_email_base_url")
    except ValueError:
        raise
    except Exception:
        raise ValueError("insecure_email_base_url") from None


def resolve_logo_path() -> Path | None:
    return LOGO_PATH if LOGO_PATH.is_file() else None


def resolve_logo_url(*, base_url: str | None = None, cfg: dict[str, Any] | None = None) -> str | None:
    """Return an absolute URL for the logo (used in <img src>, not as an attachment)."""
    if cfg:
        explicit = str(cfg.get("logo_url") or "").strip()
        if explicit:
            return explicit

    explicit = os.environ.get("EMAIL_LOGO_URL", "").strip()
    if explicit:
        return explicit

    if resolve_logo_path() is None:
        return None

    site = (base_url or os.environ.get("PUBLIC_SITE_URL", "")).strip().rstrip("/")
    if not site:
        return None

    return f"{site}{LOGO_STATIC_PATH}"


def resolve_logo_src_for_email(
    *,
    logo_url: str | None = None,
    base_url: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> str | None:
    """Prefer inline CID when the logo file exists locally."""
    if logo_url:
        return logo_url
    if resolve_logo_path() is not None:
        return LOGO_CID_REF
    return resolve_logo_url(base_url=base_url, cfg=cfg)


def load_logo_attachment() -> tuple[bytes, str] | None:
    """Return logo bytes and MIME subtype for inline CID attachment."""
    path = resolve_logo_path()
    if path is None:
        return None
    subtype = path.suffix.lstrip(".").lower()
    if subtype == "jpg":
        subtype = "jpeg"
    if subtype not in {"png", "jpeg", "gif", "webp"}:
        subtype = "png"
    return path.read_bytes(), subtype


def bilingual_footer_html() -> str:
    from accounts_app.services.project_timezone import project_local_now

    year = project_local_now().year
    return (
        f"© {year} {BRAND_NAME_EN}. جميع الحقوق محفوظة.<br>"
        f"© {year} {BRAND_NAME_EN}. All rights reserved."
    )


def bilingual_footer_plain() -> str:
    from accounts_app.services.project_timezone import project_local_now

    year = project_local_now().year
    return (
        f"© {year} {BRAND_NAME_EN}. جميع الحقوق محفوظة.\n"
        f"© {year} {BRAND_NAME_EN}. All rights reserved."
    )


def _outlook_head_markup() -> str:
    return """<!--[if gte mso 9]>
<xml>
  <o:OfficeDocumentSettings>
    <o:AllowPNG/>
    <o:PixelsPerInch>96</o:PixelsPerInch>
  </o:OfficeDocumentSettings>
</xml>
<![endif]-->"""


def render_bilingual_block(*, text_ar: str, text_en: str) -> str:
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td dir="rtl" align="right" style="padding:0 0 16px;">{text_ar}</td></tr>'
        f'<tr><td style="border-top:1px solid {DIVIDER_COLOR};font-size:0;line-height:0;'
        f'height:1px;padding:0 0 16px;">&nbsp;</td></tr>'
        f'<tr><td dir="ltr" align="left" style="padding:0;">{text_en}</td></tr>'
        f"</table>"
    )


def render_bilingual_plain(*, text_ar: str, text_en: str) -> str:
    return f"{text_ar}\n\n---\n\n{text_en}"


def render_info_box(inner_html: str) -> str:
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        f'<tr><td align="center" style="background-color:{CONTENT_BOX_BG};'
        f'border-radius:8px;padding:22px 16px;">{inner_html}</td></tr></table>'
    )


def render_otp_code(code: str) -> str:
    safe_code = escape(code)
    return render_info_box(
        f'<span style="font-size:38px;font-weight:bold;color:{BRAND_RED};'
        f'letter-spacing:8px;font-family:Arial,Helvetica,sans-serif;">{safe_code}</span>'
    )


def render_bilingual_header(*, header_ar: str, header_en: str) -> str:
    """Table-based header rows — Outlook ignores display:block on inline spans."""
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td align="center" dir="rtl" '
        f'style="color:#ffffff;font-size:18px;font-weight:bold;'
        f'font-family:Arial,Helvetica,sans-serif;line-height:26px;padding-bottom:4px;">'
        f"{header_ar}</td></tr>"
        f'<tr><td align="center" dir="ltr" '
        f'style="color:#ffffff;font-size:16px;font-weight:600;'
        f'font-family:Arial,Helvetica,sans-serif;line-height:24px;">'
        f"{header_en}</td></tr>"
        f"</table>"
    )


def _cta_button_labels_table(*, label_ar: str, label_en: str) -> str:
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center">'
        f'<tr><td align="center" dir="rtl" '
        f'style="color:#ffffff;font-family:Arial,Helvetica,sans-serif;'
        f'font-size:16px;font-weight:bold;line-height:22px;padding-bottom:4px;">'
        f"{label_ar}</td></tr>"
        f'<tr><td align="center" dir="ltr" '
        f'style="color:#ffffff;font-family:Arial,Helvetica,sans-serif;'
        f'font-size:14px;font-weight:600;line-height:20px;">'
        f"{label_en}</td></tr>"
        f"</table>"
    )


def render_cta_button(url: str, *, label_ar: str, label_en: str) -> str:
    """Bulletproof bilingual button — table layout + VML fallback for Outlook."""
    safe_url = escape(url, quote=True)
    labels = _cta_button_labels_table(label_ar=label_ar, label_en=label_en)
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" '
        f'style="margin:20px auto 0;">'
        f"<tr><td align=\"center\">"
        f"<!--[if mso]>"
        f'<v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" '
        f'xmlns:w="urn:schemas-microsoft-com:office:office" href="{safe_url}" '
        f'style="height:56px;v-text-anchor:middle;width:260px;" arcsize="12%" '
        f'stroke="f" fillcolor="{BRAND_BLUE}">'
        f"<w:anchorlock/>"
        f'<center style="color:#ffffff;font-family:Arial,sans-serif;font-size:16px;'
        f'font-weight:bold;line-height:22px;">'
        f"{label_ar}<br>"
        f'<span style="font-size:14px;font-weight:600;">{label_en}</span>'
        f"</center></v:roundrect>"
        f"<![endif]-->"
        f"<!--[if !mso]><!-->"
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td align="center" bgcolor="{BRAND_BLUE}" '
        f'style="background-color:{BRAND_BLUE};border-radius:8px;padding:14px 28px;">'
        f'<a href="{safe_url}" target="_blank" '
        f'style="color:#ffffff;text-decoration:none;">'
        f"{labels}"
        f"</a></td></tr></table>"
        f"<!--<![endif]-->"
        f"</td></tr></table>"
    )


def build_branded_email_html(
    *,
    header_ar: str,
    header_en: str,
    body_html: str,
    logo_url: str | None = None,
    base_url: str | None = None,
) -> str:
    logo_row = ""
    resolved_logo = resolve_logo_src_for_email(logo_url=logo_url, base_url=base_url)
    if resolved_logo:
        safe_src = escape(resolved_logo, quote=True)
        logo_row = (
            f'<tr><td align="center" style="padding:28px 24px 12px;">'
            f'<img src="{safe_src}" alt="{escape(BRAND_NAME_EN)}" width="240" '
            f'style="max-width:240px;width:240px;height:auto;margin:0 auto;border:0;">'
            f"</td></tr>"
        )

    header_html = render_bilingual_header(header_ar=header_ar, header_en=header_en)
    return f"""<!DOCTYPE html>
<html lang="ar" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{header_ar} / {header_en}</title>
{_outlook_head_markup()}
</head>
<body style="margin:0;padding:0;background-color:{BODY_BG};font-family:Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{BODY_BG};padding:28px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:520px;background:{CARD_BG};border-radius:12px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,0.08);">
          {logo_row}
          <tr>
            <td align="center" bgcolor="{BRAND_BLUE}" style="background-color:{BRAND_BLUE};padding:16px 24px;">
              {header_html}
            </td>
          </tr>
          <tr>
            <td style="padding:28px 32px 24px;color:{TEXT_PRIMARY};font-size:15px;line-height:1.65;">
              {body_html}
            </td>
          </tr>
          <tr>
            <td align="center" style="background-color:{FOOTER_BG};padding:16px 24px;color:{TEXT_FOOTER};font-size:12px;line-height:1.5;">
              {bilingual_footer_html()}
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _build_branded_mime_root(*, plain: str, html: str):
    from email.mime.image import MIMEImage
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    logo_attachment = load_logo_attachment()
    use_inline_logo = logo_attachment is not None and LOGO_CID_REF in html

    if use_inline_logo:
        root = MIMEMultipart("related")
        alternative = MIMEMultipart("alternative")
        alternative.attach(MIMEText(plain, "plain", "utf-8"))
        alternative.attach(MIMEText(html, "html", "utf-8"))
        root.attach(alternative)
        logo_bytes, subtype = logo_attachment
        image = MIMEImage(logo_bytes, _subtype=subtype)
        image.add_header("Content-ID", f"<{LOGO_CID}>")
        image.add_header("Content-Disposition", "inline", filename=LOGO_FILENAME)
        root.attach(image)
        return root

    root = MIMEMultipart("alternative")
    root.attach(MIMEText(plain, "plain", "utf-8"))
    root.attach(MIMEText(html, "html", "utf-8"))
    return root


def send_branded_email_smtp(
    cfg: dict[str, Any],
    *,
    to_addr: str,
    subject: str,
    plain: str,
    html: str,
) -> None:
    from email.header import Header
    from email.utils import formataddr

    to_addr = to_addr.strip()
    host = str(cfg.get("host", "")).strip()
    from_addr = str(cfg.get("from", "")).strip()
    if not host or not from_addr:
        raise ValueError("smtp_incomplete_config")

    msg = _build_branded_mime_root(plain=plain, html=html)

    msg["Subject"] = Header(truncate_email_subject(subject), "utf-8")
    from_name = resolve_from_name(cfg)
    if from_name:
        msg["From"] = formataddr((str(Header(from_name, "utf-8")), from_addr))
    else:
        msg["From"] = from_addr
    enrich_message_headers(msg, cfg, from_addr=from_addr, to_addr=to_addr)

    _smtp_send_message(cfg, from_addr=from_addr, to_addr=to_addr, msg=msg)


def send_plain_email_smtp(
    cfg: dict[str, Any],
    *,
    to_addr: str,
    subject: str,
    plain: str,
) -> None:
    from email.header import Header
    from email.mime.text import MIMEText
    from email.utils import formataddr

    to_addr = to_addr.strip()
    host = str(cfg.get("host", "")).strip()
    from_addr = str(cfg.get("from", "")).strip()
    if not host or not from_addr:
        raise ValueError("smtp_incomplete_config")

    msg = MIMEText(plain, "plain", "utf-8")
    msg["Subject"] = Header(truncate_email_subject(subject), "utf-8")
    from_name = resolve_from_name(cfg)
    if from_name:
        msg["From"] = formataddr((str(Header(from_name, "utf-8")), from_addr))
    else:
        msg["From"] = from_addr
    enrich_message_headers(msg, cfg, from_addr=from_addr, to_addr=to_addr)

    _smtp_send_message(cfg, from_addr=from_addr, to_addr=to_addr, msg=msg)
