"""Admin site customizations (disable per-app index pages)."""

from __future__ import annotations

from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import reverse

# Fixed admin sidebar order: auth → audit_app → accounts_app → others (alpha).
ADMIN_SIDEBAR_APP_ORDER = ("auth", "audit_app", "accounts_app")


def _sort_admin_app_list(app_list: list[dict]) -> list[dict]:
    order = {label: index for index, label in enumerate(ADMIN_SIDEBAR_APP_ORDER)}

    def sort_key(app: dict) -> tuple[int, str]:
        label = str(app.get("app_label") or "")
        if label in order:
            return (0, str(order[label]).zfill(3))
        return (1, label)

    return sorted(app_list, key=sort_key)


def patch_admin_site_sidebar_order() -> None:
    """Keep sidebar sections in auth → Excel Audit → Accounts order."""

    if getattr(admin.site, "_sidebar_order_patched", False):
        return

    original_get_app_list = admin.site.get_app_list

    def get_app_list(request, app_label=None):
        app_list = original_get_app_list(request, app_label=app_label)
        if app_label is not None:
            return app_list
        return _sort_admin_app_list(app_list)

    admin.site.get_app_list = get_app_list
    admin.site._sidebar_order_patched = True


def patch_admin_site_app_index() -> None:
    """Redirect /admin/<app_label>/ to the main admin dashboard."""

    if getattr(admin.site, "_app_index_redirect_patched", False):
        return

    original_app_index = admin.site.app_index

    def app_index_redirect(request, app_label, extra_context=None):
        return HttpResponseRedirect(reverse("admin:index"))

    admin.site.app_index = app_index_redirect
    admin.site._app_index_redirect_patched = True


def patch_admin_site_index_stats() -> None:
    """Inject company/user counts into the admin index page context."""

    if getattr(admin.site, "_index_stats_patched", False):
        return

    original_index = admin.site.index

    def index_with_stats(request, extra_context=None):
        from audit_app.admin_index_stats import build_admin_index_stat_groups

        extra_context = dict(extra_context or {})
        extra_context["index_stat_groups"] = build_admin_index_stat_groups(
            request.user
        )
        return original_index(request, extra_context=extra_context)

    admin.site.index = index_with_stats
    admin.site._index_stats_patched = True
