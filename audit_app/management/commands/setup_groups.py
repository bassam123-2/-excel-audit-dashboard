"""
Management command: setup_groups

Creates the three application groups with the correct permissions.
Safe to re-run — uses get_or_create.

Groups:
  1. مديرو المستخدمين  (User Managers)
     — Can add / change / delete / view users + assign permissions / groups
     — Cannot edit the default superadmin (enforced in UserAdmin)

  2. رافعو الملفات  (File Uploaders)
     — Can upload Excel files and create dashboards

  3. مشاهدو اللوحات  (Dashboard Viewers)
     — Can view saved dashboards

Usage:
    python manage.py setup_groups
"""
from __future__ import annotations

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Creates the three application groups with the correct permissions."

    GROUPS: list[tuple[str, list[str]]] = [
        (
            "مديرو المستخدمين",
            [
                # User management
                "auth.add_user",
                "auth.change_user",
                "auth.delete_user",
                "auth.view_user",
                # Group management (so they can assign groups to users)
                "auth.add_group",
                "auth.change_group",
                "auth.delete_group",
                "auth.view_group",
                # Permission viewing (read-only, no codename change)
                "auth.view_permission",
                # Dashboard review (approve / reject)
                "audit_app.can_review_dashboards",
                "audit_app.can_delete_dashboards",
            ],
        ),
        (
            "رافعو الملفات",
            [
                "audit_app.can_upload_files",
            ],
        ),
        (
            "مشاهدو اللوحات",
            [
                "audit_app.can_view_dashboards",
            ],
        ),
    ]

    def handle(self, *args, **options) -> None:
        created_count = 0
        updated_count = 0

        for group_name, perm_paths in self.GROUPS:
            group, was_created = Group.objects.get_or_create(name=group_name)
            action = "created" if was_created else "updated"
            if was_created:
                created_count += 1
            else:
                updated_count += 1

            perms = []
            for path in perm_paths:
                app_label, codename = path.split(".")
                try:
                    p = Permission.objects.get(
                        codename=codename,
                        content_type__app_label=app_label,
                    )
                    perms.append(p)
                except Permission.DoesNotExist:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [skip] Permission not found: {path} — run migrations first."
                        )
                    )

            group.permissions.set(perms)
            perm_labels = ", ".join(p.codename for p in perms)
            self.stdout.write(
                self.style.SUCCESS(f"[{action}] group #{group.pk} -> {perm_labels}")
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone - {created_count} group(s) created, {updated_count} updated."
            )
        )

        # ── Seed default dashboard template types ───────────────────
        from audit_app.models import DashboardTemplateType
        defaults = [
            {
                "code": "ai",
                "name": "لوحة تحليلية ذكية",
                "description": "لوحة تحكم مبنية بالذكاء الاصطناعي تعرض مؤشرات التدقيق الداخلي",
                "icon": "bi-stars",
                "sort_order": 1,
            },
        ]
        for d in defaults:
            code = d.pop("code")
            obj, was_created = DashboardTemplateType.objects.get_or_create(
                code=code, defaults=d
            )
            action = "seeded" if was_created else "exists"
            self.stdout.write(f"  [{action}] template type: {code}")
