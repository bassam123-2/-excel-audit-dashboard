"""Report duplicate auth user emails (case-insensitive)."""
from __future__ import annotations

from collections import defaultdict

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "List duplicate user emails (case-insensitive). Exit 1 if any found."

    def handle(self, *args, **options):
        User = get_user_model()
        buckets: dict[str, list] = defaultdict(list)
        for user in User.objects.exclude(email="").only("id", "username", "email"):
            key = user.email.strip().lower()
            if key:
                buckets[key].append(user)

        duplicates = {k: v for k, v in buckets.items() if len(v) > 1}
        if not duplicates:
            self.stdout.write(self.style.SUCCESS("No duplicate emails found."))
            return

        self.stdout.write(self.style.ERROR(f"Found {len(duplicates)} duplicate email(s):"))
        for email, users in duplicates.items():
            self.stdout.write(f"  {email}:")
            for user in users:
                self.stdout.write(f"    - id={user.pk} username={user.username}")
        raise SystemExit(1)
