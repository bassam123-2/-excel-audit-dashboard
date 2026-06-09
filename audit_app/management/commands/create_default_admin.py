"""
Management command: create_default_admin

Creates the default superuser account (myadmin / Admin@1234) if it does not exist.
Safe to re-run — skips creation when the user already exists.

Usage:
    python manage.py create_default_admin
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Creates the default superuser (myadmin) if it does not already exist."

    DEFAULT_USERNAME = "myadmin"
    DEFAULT_PASSWORD = "Admin@1234"
    DEFAULT_EMAIL = "admin@localhost"

    def handle(self, *args, **options) -> None:
        # Ensure groups exist before creating the admin
        from django.core.management import call_command
        call_command("setup_groups", verbosity=0)

        username = self.DEFAULT_USERNAME

        if User.objects.filter(username=username).exists():
            self.stdout.write(
                self.style.WARNING(
                    f"[skip] Superuser '{username}' already exists — no changes made."
                )
            )
            return

        User.objects.create_superuser(
            username=username,
            email=self.DEFAULT_EMAIL,
            password=self.DEFAULT_PASSWORD,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"[ok] Superuser '{username}' created with the default password.\n"
                f"     Please change the password after first login."
            )
        )
