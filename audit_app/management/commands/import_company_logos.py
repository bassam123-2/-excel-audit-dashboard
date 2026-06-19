from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand

from audit_app.models import COMPANY_KIND_MAIN, COMPANY_KIND_SUBSIDIARY, Company

_LOGO_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


class Command(BaseCommand):
    help = "Import company logos from assets/logos/ into Company.logo records."

    def handle(self, *args, **options):
        logos_dir = Path(settings.BASE_DIR) / "assets" / "logos"
        if not logos_dir.is_dir():
            self.stderr.write(self.style.ERROR(f"Directory not found: {logos_dir}"))
            return

        imported = 0
        for company in Company.objects.filter(company_kind=COMPANY_KIND_MAIN):
            if company.logo:
                continue
            logo_path = self._find_logo_file(logos_dir, company.code)
            if logo_path and self._assign_logo(company, logo_path):
                imported += 1
                self.stdout.write(self.style.SUCCESS(f"Imported logo for {company.code}"))

        for company in Company.objects.filter(company_kind=COMPANY_KIND_SUBSIDIARY):
            if company.logo or not company.parent_id:
                continue
            parent_dir = logos_dir / company.parent.code
            logo_path = self._find_logo_file(parent_dir, company.code) if parent_dir.is_dir() else None
            if logo_path is None:
                logo_path = self._find_logo_file(logos_dir, company.code)
            if logo_path and self._assign_logo(company, logo_path):
                imported += 1
                self.stdout.write(
                    self.style.SUCCESS(f"Imported logo for subsidiary {company.code}")
                )

        self.stdout.write(self.style.SUCCESS(f"Done. {imported} logo(s) imported."))

    def _find_logo_file(self, directory: Path, code: str) -> Path | None:
        if not directory.is_dir():
            return None
        for ext in _LOGO_EXTS:
            candidate = directory / f"{code}{ext}"
            if candidate.is_file():
                return candidate
            candidate = directory / f"{code.lower()}{ext}"
            if candidate.is_file():
                return candidate
            candidate = directory / f"{code.upper()}{ext}"
            if candidate.is_file():
                return candidate
        return None

    def _assign_logo(self, company: Company, logo_path: Path) -> bool:
        with logo_path.open("rb") as fh:
            company.logo.save(logo_path.name, File(fh), save=True)
        return True
