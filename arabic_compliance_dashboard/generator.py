"""Build HTML report and offline export for Arabic compliance dashboard."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .engine import build_snapshot_pack
from .schema import normalize_dataframe, rows_from_dataframe

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
REPORT_VERSION = "ar_compliance_1"


def _read_asset(name: str) -> str:
    return (ASSETS_DIR / name).read_text(encoding="utf-8")


def _json_script_tag(data: Any, element_id: str) -> str:
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return f'<script type="application/json" id="{element_id}">{payload}</script>'


def _body_with_header_logo(
    body: str,
    brand_logos: dict[str, str] | None,
    default_brand_code: str | None,
) -> str:
    """Embed the tenant main-company logo in the header (independent of subsidiary filters)."""
    code = (default_brand_code or "").strip().lower()
    if not code:
        return body
    uri = (brand_logos or {}).get(code)
    if not uri:
        return body
    hidden_tag = '<img id="headerLogo" class="logo" alt="" hidden>'
    visible_tag = f'<img id="headerLogo" class="logo" alt="" src="{uri}">'
    if hidden_tag in body:
        return body.replace(hidden_tag, visible_tag, 1)
    return body


def generate_ar_compliance_report(
    df: pd.DataFrame,
    *,
    dashboard_id: int,
    api_base: str | None = None,
    embed_snapshot: bool = False,
    brand_logos: dict[str, str] | None = None,
    default_brand_code: str | None = None,
) -> str:
    """Return full HTML document for iframe serve or export."""
    normalized = normalize_dataframe(df)
    rows = rows_from_dataframe(normalized)
    pack = build_snapshot_pack(
        rows,
        brand_logos=brand_logos or {},
        default_brand_code=default_brand_code,
    )

    api_base = (api_base or f"/dashboards/{dashboard_id}/ar-api").rstrip("/")
    css = _read_asset("styles.css")
    body = _body_with_header_logo(
        _read_asset("body.html"),
        brand_logos,
        default_brand_code,
    )
    js = _read_asset("dashboard.js")

    config_script = (
        "<script>window.__AR_DASHBOARD__ = "
        + json.dumps(
            {
                "dashboardId": dashboard_id,
                "apiBase": api_base,
                "isLive": not embed_snapshot,
            },
            ensure_ascii=False,
        )
        + ";</script>"
    )

    extra_scripts = ""
    extra_scripts += _json_script_tag(pack, "snapshot-pack")
    extra_scripts += _json_script_tag(
        {
            "sheetName": "",
            "headers": [],
            "rows": [],
            "styles": {},
            "selectedCell": None,
        },
        "compliance-plan-seed",
    )

    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>نتائج التحليل</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2"></script>
    <script src="https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js"></script>
    <style>
{css}
    </style>
</head>
<body>
{body}
{extra_scripts}
{config_script}
    <script>
{js}
    </script>
</body>
</html>"""


def export_snapshot_html(
    df: pd.DataFrame,
    *,
    dashboard_id: int,
    brand_logos: dict[str, str] | None = None,
    default_brand_code: str | None = None,
) -> str:
    """Self-contained interactive HTML (offline fetch shim active)."""
    return generate_ar_compliance_report(
        df,
        dashboard_id=dashboard_id,
        api_base="",
        embed_snapshot=True,
        brand_logos=brand_logos,
        default_brand_code=default_brand_code,
    )
