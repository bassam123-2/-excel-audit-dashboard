"""Site-wide utility views."""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.templatetags.static import static

from config.robots import ROBOTS_TXT


def robots_txt(_request):
    return HttpResponse(ROBOTS_TXT, content_type="text/plain; charset=utf-8")


def web_app_manifest(_request):
    """
    Serve the PWA web app manifest outside /static/.

    Hashed ``manifest.*.json`` under STATIC_URL often returns 403 on VPS
    setups that deny public ``.json`` under the static location. Serving
    ``/manifest.webmanifest`` from Django avoids that block.
    """
    payload = _load_web_app_manifest_payload()
    return HttpResponse(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        content_type="application/manifest+json; charset=utf-8",
    )


def _load_web_app_manifest_payload() -> dict:
    path = Path(settings.BASE_DIR) / "assets" / "manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        data = {
            "name": "Audit Dashboard",
            "short_name": "Audit",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#0f1f3d",
            "theme_color": "#2563eb",
            "lang": "ar",
            "icons": [],
        }

    if not isinstance(data, dict):
        data = {}

    icons = data.get("icons")
    if not isinstance(icons, list) or not icons:
        data["icons"] = [
            {
                "src": static("admin/img/icon-addlink.svg"),
                "sizes": "192x192",
                "type": "image/svg+xml",
            }
        ]
    else:
        rewritten = []
        for icon in icons:
            if not isinstance(icon, dict):
                continue
            item = dict(icon)
            src = str(item.get("src") or "").strip()
            if src.startswith("/static/"):
                # Resolve through storage so Manifest hashes apply when needed.
                rel = src[len("/static/") :]
                item["src"] = static(rel)
            rewritten.append(item)
        data["icons"] = rewritten or [
            {
                "src": static("admin/img/icon-addlink.svg"),
                "sizes": "192x192",
                "type": "image/svg+xml",
            }
        ]
    return data
