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
