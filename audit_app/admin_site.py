"""Admin site customizations (disable per-app index pages)."""

from __future__ import annotations

from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import reverse


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
        from django.contrib.auth import get_user_model

        from audit_app.models import Company

        extra_context = dict(extra_context or {})
        extra_context["index_companies_count"] = Company.objects.filter(
            is_deleted=False
        ).count()
        extra_context["index_users_count"] = (
            get_user_model().objects.exclude(profile__is_deleted=True).count()
        )
        return original_index(request, extra_context=extra_context)

    admin.site.index = index_with_stats
    admin.site._index_stats_patched = True
