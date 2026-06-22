"""Patch extracted Arabic dashboard assets for Django live mode."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "arabic_compliance_dashboard" / "assets"


def patch_body() -> None:
    body_path = ASSETS / "body.html"
    body = body_path.read_text(encoding="utf-8")
    body = re.sub(
        r'<img id="headerLogo" class="logo" alt="" src="data:image[^"]*">',
        '<img id="headerLogo" class="logo" alt="" hidden>',
        body,
        count=1,
    )
    body_path.write_text(body, encoding="utf-8")


def patch_js() -> None:
    js_path = ASSETS / "dashboard.js"
    js = js_path.read_text(encoding="utf-8")
    prefix = (
        "const __arCfg = window.__AR_DASHBOARD__ || {};\n"
        '        const __arApiBase = String(__arCfg.apiBase || "").replace(/\\/+$/, "");\n'
        "        function arApiUrl(path) {\n"
        '            const p = path.startsWith("/") ? path : "/" + path;\n'
        "            if (__arApiBase) return __arApiBase + p;\n"
        '            return "/api" + (p.startsWith("/api") ? p.slice(4) : p);\n'
        "        }\n\n        "
    )
    if "function arApiUrl" not in js:
        js = prefix + js
    replacements = [
        ("`/api/summary?", "`${arApiUrl('/summary')}?"),
        ("`/api/aging-summary?", "`${arApiUrl('/aging-summary')}?"),
        ("`/api/legal-text-row-images?", "`${arApiUrl('/legal-text-row-images')}?"),
        ("`/api/export-dashboard-html?", "`${arApiUrl('/export-dashboard-html')}?"),
        ("`/api/brand-logo?", "`${arApiUrl('/brand-logo')}?"),
        ('"/api/send-legal-text-email"', "arApiUrl('/send-legal-text-email')"),
        ('"/api/export-legal-text-pptx"', "arApiUrl('/export-legal-text-pptx')"),
        ('"/api/legal-text-details"', "arApiUrl('/legal-text-details')"),
    ]
    for old, new in replacements:
        js = js.replace(old, new)
    js_path.write_text(js, encoding="utf-8")


def main() -> None:
    patch_body()
    patch_js()
    print("Patched Arabic dashboard assets.")


if __name__ == "__main__":
    main()
