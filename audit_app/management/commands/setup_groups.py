"""
Management command: setup_groups

Creates the admin group for user management (Django auth permissions only).
Dashboard upload/view/review/delete are configured per company in Company memberships.

Usage:
    python manage.py setup_groups
"""
from __future__ import annotations

from django.contrib.auth.models import Group, Permission, User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Creates admin groups (user management only — not dashboard company permissions)."

    GROUPS: list[tuple[str, list[str]]] = [
        (
            "مديرو المستخدمين",
            [
                "auth.add_user",
                "auth.change_user",
                "auth.delete_user",
                "auth.view_user",
                "auth.add_group",
                "auth.change_group",
                "auth.delete_group",
                "auth.view_group",
                "auth.view_permission",
            ],
        ),
    ]

    LEGACY_GROUP_NAMES = (
        "رافعو الملفات",
        "مشاهدو اللوحات",
    )

    LEGACY_DASHBOARD_PERMISSIONS = (
        "audit_app.can_upload_files",
        "audit_app.can_view_dashboards",
        "audit_app.can_review_dashboards",
        "audit_app.can_delete_dashboards",
    )

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

        for legacy_name in self.LEGACY_GROUP_NAMES:
            deleted, _ = Group.objects.filter(name=legacy_name).delete()
            if deleted:
                self.stdout.write(
                    self.style.WARNING(f"[removed] legacy group: {legacy_name}")
                )

        legacy_perms = list(
            Permission.objects.filter(
                content_type__app_label="audit_app",
                content_type__model="dashboard",
            )
        )
        if legacy_perms:
            for group in Group.objects.filter(permissions__in=legacy_perms).distinct():
                group.permissions.remove(*legacy_perms)
                self.stdout.write(
                    self.style.WARNING(
                        f"[cleaned] removed legacy dashboard permissions from group: {group.name}"
                    )
                )
            for user in User.objects.filter(user_permissions__in=legacy_perms).distinct():
                user.user_permissions.remove(*legacy_perms)
                self.stdout.write(
                    self.style.WARNING(
                        f"[cleaned] removed legacy dashboard permissions from user: {user.username}"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone - {created_count} group(s) created, {updated_count} updated."
            )
        )
        self.stdout.write(
            self.style.NOTICE(
                "Dashboard permissions (upload/view/review/draft delete) "
                "are set per company in User → Company memberships."
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
