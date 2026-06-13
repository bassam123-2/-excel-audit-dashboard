from __future__ import annotations

from django.core.management.base import BaseCommand

from audit_app.models import Company

DEFAULT_COMPANIES = [
    {"code": "BTC", "name": "BTC"},
    {"code": "NAT", "name": "NAT"},
    {"code": "AUM", "name": "AUM"},
    {"code": "SACO", "name": "SACO"},
]


class Command(BaseCommand):
    help = "Seed default tenant companies (BTC, NAT, AUM, SACO) with all attachments enabled."

    def handle(self, *args, **options):
        created = 0
        for item in DEFAULT_COMPANIES:
            company, was_created = Company.objects.get_or_create(
                code=item["code"],
                defaults={
                    "name": item["name"],
                    "excel_company_names": [item["code"]],
                    "is_active": True,
                },
            )
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f"Created company {company.code}"))
            else:
                self.stdout.write(f"Company {company.code} already exists")
            company.ensure_attachment_settings()

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {created} new company/companies; attachment settings ensured for all."
            )
        )
