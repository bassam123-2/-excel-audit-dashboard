"""Fail deploy when collectstatic is not using hashed Manifest storage."""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.management.base import BaseCommand, CommandError

# Representative CSS files that must receive content hashes in production.
REQUIRED_STATIC = (
    "admin/custom.css",
    "css/admin_change_form_v2.css",
    "css/dashboard-pages.css",
)


class Command(BaseCommand):
    help = (
        "Verify Manifest static storage so CSS/JS URLs change after deploy. "
        "Use --verify-files after collectstatic."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--verify-files",
            action="store_true",
            help="Require hashed copies of key CSS files under STATIC_ROOT.",
        )

    def handle(self, *args, **options):
        backend = str(
            settings.STORAGES.get("staticfiles", {}).get("BACKEND", "")
        )
        if "Manifest" not in backend:
            raise CommandError(
                "staticfiles backend is %r (expected Manifest). "
                "collectstatic under development settings copies unhashed files "
                "and leaves hashed CSS stale. Set "
                "DJANGO_SETTINGS_MODULE=config.settings.production "
                "(module path only — no gunicorn command on that line)."
                % backend
            )
        if settings.DEBUG:
            raise CommandError(
                "DEBUG=True during static deploy check. "
                "Set DJANGO_DEBUG=false and use config.settings.production."
            )

        self.stdout.write(
            f"OK Manifest backend={backend} "
            f"DEBUG={settings.DEBUG} "
            f"module={settings.SETTINGS_MODULE}"
        )

        if not options["verify_files"]:
            return

        root = Path(settings.STATIC_ROOT)
        for name in REQUIRED_STATIC:
            stored = staticfiles_storage.stored_name(name)
            if stored == name:
                raise CommandError(
                    "%s was not hashed (%s). collectstatic did not run with "
                    "Manifest storage." % (name, stored)
                )
            path = root / stored
            if not path.is_file():
                raise CommandError("Missing hashed static file: %s" % path)
            self.stdout.write(f"  {name} -> {stored}")
        self.stdout.write(self.style.SUCCESS("Hashed static files present."))
