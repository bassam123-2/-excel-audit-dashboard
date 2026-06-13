from __future__ import annotations

import hashlib
import secrets
from typing import Any

from django.core.cache import cache

OTP_TTL_SECONDS = 600
OTP_MAX_ATTEMPTS = 5
OTP_LENGTH = 6


def _cache_key(user_id: int) -> str:
    return f"2fa_otp:{user_id}"


def _hash_otp(user_id: int, code: str) -> str:
    return hashlib.sha256(f"{user_id}:{code}".encode()).hexdigest()


def generate_and_store_otp(user_id: int) -> str:
    code = "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))
    payload = {"hash": _hash_otp(user_id, code), "attempts": 0}
    cache.set(_cache_key(user_id), payload, OTP_TTL_SECONDS)
    return code


def verify_otp(user_id: int, code: str) -> bool:
    payload = cache.get(_cache_key(user_id))
    if not payload:
        return False
    attempts = int(payload.get("attempts", 0))
    if attempts >= OTP_MAX_ATTEMPTS:
        cache.delete(_cache_key(user_id))
        return False
    normalized = str(code or "").strip()
    if not normalized or len(normalized) != OTP_LENGTH or not normalized.isdigit():
        payload["attempts"] = attempts + 1
        cache.set(_cache_key(user_id), payload, OTP_TTL_SECONDS)
        return False
    if payload.get("hash") != _hash_otp(user_id, normalized):
        payload["attempts"] = attempts + 1
        cache.set(_cache_key(user_id), payload, OTP_TTL_SECONDS)
        return False
    cache.delete(_cache_key(user_id))
    return True


def clear_otp(user_id: int) -> None:
    cache.delete(_cache_key(user_id))


def send_otp_email_smtp(cfg: dict[str, Any], *, to_addr: str, code: str, locale: str) -> None:
    from email.header import Header
    from email.mime.text import MIMEText
    from email.utils import formataddr
    import smtplib

    to_addr = to_addr.strip()
    if locale == "ar":
        subject = "رمز التحقق — لوحة المراجعة"
        body = (
            "السلام عليكم،\n\n"
            f"رمز التحقق الخاص بك هو: {code}\n\n"
            "صالح لمدة 10 دقائق.\n"
            "إذا لم تطلب هذا الرمز، تجاهل هذه الرسالة.\n"
        )
    else:
        subject = "Verification code — Audit Dashboard"
        body = (
            "Hello,\n\n"
            f"Your verification code is: {code}\n\n"
            "It is valid for 10 minutes.\n"
            "If you did not request this code, please ignore this email.\n"
        )

    host = str(cfg.get("host", "")).strip()
    from_addr = str(cfg.get("from", "")).strip()
    if not host or not from_addr:
        raise ValueError("smtp_incomplete_config")

    port = int(cfg.get("port", 587))
    use_tls = bool(cfg.get("use_tls", True))
    user = str(cfg.get("username") or cfg.get("user") or from_addr).strip()
    password = str(cfg.get("password", ""))

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    from_name = str(cfg.get("from_name") or cfg.get("sender_name") or "Audit Dashboard").strip()
    if from_name:
        msg["From"] = formataddr((str(Header(from_name, "utf-8")), from_addr))
    else:
        msg["From"] = from_addr
    msg["To"] = to_addr

    if use_tls:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            if user and password:
                smtp.login(user, password)
            smtp.sendmail(from_addr, [to_addr], msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            if user and password:
                smtp.login(user, password)
            smtp.sendmail(from_addr, [to_addr], msg.as_string())


def initiate_two_factor(user, locale: str) -> None:
    from ai_excel_dashboard import load_smtp_config

    email = (user.email or "").strip()
    if not email:
        raise ValueError("no_email_for_2fa")
    cfg = load_smtp_config()
    if not cfg:
        raise ValueError("smtp_not_configured")
    code = generate_and_store_otp(user.pk)
    send_otp_email_smtp(cfg, to_addr=email, code=code, locale=locale)
