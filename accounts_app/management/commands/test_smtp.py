"""
Test SMTP configuration and optionally send a probe email.

Usage:
    python manage.py test_smtp
    python manage.py test_smtp --to info@example.com
    python manage.py test_smtp --send-otp-style
"""
from __future__ import annotations

import smtplib
from email.mime.text import MIMEText

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from ai_excel_dashboard import load_smtp_config


class Command(BaseCommand):
    help = "Verify SMTP settings from .env and optionally send a test message."

    def add_arguments(self, parser):
        parser.add_argument(
            "--to",
            dest="to_addr",
            default="",
            help="Recipient email (default: myadmin user email, or SMTP FROM address).",
        )
        parser.add_argument(
            "--send-otp-style",
            action="store_true",
            help="Send a message using the same helper as login 2FA.",
        )

    def handle(self, *args, **options):
        cfg = load_smtp_config()
        if not cfg:
            raise CommandError(
                "SMTP not configured. Set AI_EXCEL_SMTP_HOST, AI_EXCEL_SMTP_USER, "
                "AI_EXCEL_SMTP_PASSWORD, and AI_EXCEL_SMTP_FROM in .env, then restart the server."
            )

        host = str(cfg.get("host", ""))
        port = int(cfg.get("port", 587))
        user = str(cfg.get("username") or cfg.get("user") or cfg.get("from", ""))
        from_addr = str(cfg.get("from", ""))
        use_tls = bool(cfg.get("use_tls", True))

        self.stdout.write(f"Host:     {host}")
        self.stdout.write(f"Port:     {port}")
        self.stdout.write(f"User:     {user}")
        self.stdout.write(f"From:     {from_addr}")
        self.stdout.write(f"TLS:      {use_tls}")

        to_addr = (options.get("to_addr") or "").strip()
        if not to_addr:
            admin = User.objects.filter(username="myadmin").first()
            to_addr = (admin.email if admin and admin.email else "") or from_addr
        if not to_addr:
            raise CommandError("No recipient. Pass --to your@email.com")

        self.stdout.write(f"To:       {to_addr}")
        self.stdout.write("Connecting…")

        try:
            smtp = smtplib.SMTP(host, port, timeout=30)
            smtp.ehlo()
            if use_tls:
                smtp.starttls()
                smtp.ehlo()
            smtp.login(user, str(cfg.get("password", "")))
            self.stdout.write(self.style.SUCCESS("[ok] SMTP login succeeded"))
        except Exception as exc:
            raise CommandError(f"SMTP login failed: {exc}") from exc

        if options.get("send_otp_style"):
            smtp.quit()
            from accounts_app.services.two_factor import send_otp_email_smtp

            try:
                send_otp_email_smtp(
                    cfg, to_addr=to_addr, code="123456", locale="ar"
                )
            except Exception as exc:
                raise CommandError(f"2FA-style send failed: {exc}") from exc
            self.stdout.write(
                self.style.SUCCESS(
                    f"[ok] 2FA-style OTP email sent to {to_addr}. Check inbox and spam."
                )
            )
            return

        msg = MIMEText(
            "This is a test message from excel-audit-dashboard (manage.py test_smtp).\n",
            "plain",
            "utf-8",
        )
        msg["Subject"] = "SMTP test — Audit Dashboard"
        msg["From"] = from_addr
        msg["To"] = to_addr

        try:
            refused = smtp.sendmail(from_addr, [to_addr], msg.as_string())
            smtp.quit()
        except Exception as exc:
            raise CommandError(f"Send failed: {exc}") from exc

        if refused:
            raise CommandError(f"Server refused recipient(s): {refused}")

        self.stdout.write(
            self.style.SUCCESS(
                f"[ok] Test email accepted by SMTP server for {to_addr}.\n"
                "     If it does not arrive within a few minutes, check spam/junk "
                "and your mail server delivery logs."
            )
        )
