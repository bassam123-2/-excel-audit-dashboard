from __future__ import annotations

import os
import sys

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from django.utils import translation

from web_strings import get_ui


def ui_context(request) -> dict:
    """
    Injects into every template context:
      lang, is_rtl, dir, ui              — language & translations
      can_upload_files, can_view_dashboards  — permission booleans (safe in templates)
    """
    lang = (
        request.session.get("ui_lang")
        or translation.get_language()
        or "ar"
    )
    lang = str(lang).split("-")[0]
    lang = "ar" if lang not in ("ar", "en") else lang
    can_upload = False
    can_view = False
    can_manage_users = False
    can_delete_dashboards = False
    if hasattr(request, "user") and request.user.is_authenticated:
        u = request.user
        can_upload = u.is_staff or u.is_superuser or u.has_perm("audit_app.can_upload_files")
        can_view = (
            u.is_staff or u.is_superuser
            or u.has_perm("audit_app.can_view_dashboards")
            or u.has_perm("audit_app.can_upload_files")
        )
        can_delete_dashboards = (
            u.is_staff or u.is_superuser
            or u.has_perm("audit_app.can_delete_dashboards")
        )
        can_manage_users = u.is_superuser or u.has_perm("auth.change_user")

    return {
        "lang": lang,
        "is_rtl": lang == "ar",
        "dir": "rtl" if lang == "ar" else "ltr",
        "ui": get_ui(lang),
        "can_upload_files": can_upload,
        "can_view_dashboards": can_view,
        "can_delete_dashboards": can_delete_dashboards,
        "can_manage_users": can_manage_users,
    }
