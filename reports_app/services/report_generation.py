from __future__ import annotations

import html
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from django.http import HttpResponse
from django.utils.text import slugify

from ai_excel_dashboard import (
    _MAIL_API_MARKER,
    _PLAN_PARSE_API_MARKER,
    AUDIT_BUNDLE_MAX_FILES,
    REPORT_VERSION,
    build_multi_dashboard_shell,
    content_fingerprint,
    generate_finance_report,
    resolve_attached_deck_for_workbook_index,
    workbook_dashboard_tab_title,
)
from audit_app.services.persistence import persist_report_result
from dashboard_locale import normalize_locale, tr
from data_io import read_input_file
from exact_dashboard import render_from_reference
from export_bundle import build_summary_pptx, create_export_zip

REFERENCE_DASHBOARD = os.environ.get("EXACT_DASHBOARD_TEMPLATE", "").strip()


def html_no_cache_response(text: str, status: int = 200) -> HttpResponse:
    response = HttpResponse(
        text, status=status, content_type="text/html; charset=utf-8"
    )
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    return response


def inject_web_mail_api(html_out: str, mail_url: str, plan_url: str) -> str:
    try:
        h = html_out.replace(
            _MAIL_API_MARKER, f"window.__AI_EXCEL_MAIL_API__={json.dumps(mail_url)};"
        )
        h = h.replace(
            _PLAN_PARSE_API_MARKER,
            f"window.__AI_EXCEL_PLAN_PARSE_URL__={json.dumps(plan_url)};",
        )
        return h
    except Exception:
        return html_out


def excel_uploads_from_request(request) -> list:
    files = []
    for key in ("file1", "file2", "file3", "file4"):
        f = request.FILES.get(key)
        if f and str(getattr(f, "name", "")).strip():
            files.append(f)
    return files[:AUDIT_BUNDLE_MAX_FILES]


def deck_uploads_from_request(request, prefix: str = "deck") -> list:
    files = []
    for key in (f"{prefix}1", f"{prefix}2", f"{prefix}3", f"{prefix}4"):
        f = request.FILES.get(key)
        if f and str(getattr(f, "name", "")).strip():
            files.append(f)
    return files[:AUDIT_BUNDLE_MAX_FILES]


def _persist_upload(upload, tmp_dir: str) -> str:
    ext = Path(upload.name).suffix.lower()
    if ext not in {".xlsx", ".xls", ".xlsm", ".csv", ".pptx", ".ppt", ".pdf"}:
        raise ValueError("Unsupported file type.")
    stem = slugify(Path(upload.name).stem) or "upload"
    out_path = os.path.join(tmp_dir, f"{stem}{ext}")
    with open(out_path, "wb") as fh:
        for chunk in upload.chunks():
            fh.write(chunk)
    return out_path


def upload_form_html(locale: str = "en") -> str:
    from web_app import upload_form_html as flask_upload_form_html

    return flask_upload_form_html(locale)


def build_response_for_request(request) -> HttpResponse:
    locale = normalize_locale(request.POST.get("lang"))
    mode = (request.POST.get("mode") or "ai").strip().lower()
    sheet = (request.POST.get("sheet") or "").strip() or None
    uploads = excel_uploads_from_request(request)
    if not uploads:
        return HttpResponse(tr(locale, "web_err_no_file"), status=400)
    if len(uploads) > AUDIT_BUNDLE_MAX_FILES:
        return HttpResponse(
            tr(locale, "web_err_too_many_files", max=AUDIT_BUNDLE_MAX_FILES), status=400
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        dfs = []
        names = []
        for up in uploads:
            path = _persist_upload(up, tmp_dir)
            df = read_input_file(path, sheet=sheet, locale=locale)
            if df.empty:
                return HttpResponse(tr(locale, "web_err_empty"), status=400)
            dfs.append(df)
            names.append(up.name)

        deck_slots = [None, None, None, None]
        for i, d in enumerate(deck_uploads_from_request(request, "deck")):
            deck_slots[i] = _persist_upload(d, tmp_dir)
        high_risk_slots = [None, None, None, None]
        for i, d in enumerate(deck_uploads_from_request(request, "high_risk_deck")):
            high_risk_slots[i] = _persist_upload(d, tmp_dir)

        def deck_for_file_idx(i: int) -> str | None:
            nn = [p for p in deck_slots if p]
            if len(nn) == 1:
                return nn[0]
            if i < len(deck_slots):
                return deck_slots[i]
            return None

        def high_risk_for_file_idx(i: int) -> str | None:
            return resolve_attached_deck_for_workbook_index(
                [p for p in high_risk_slots if p], i, len(uploads)
            )

        if mode == "ai" and len(uploads) > 1:
            pages = []
            for i, df in enumerate(dfs):
                title = workbook_dashboard_tab_title(df, names[i])
                html_i, audit_payload = generate_finance_report(
                    df,
                    source_name=names[i],
                    sheet_name=sheet,
                    locale=locale,
                    attached_deck_path=deck_for_file_idx(i),
                    attached_high_risk_deck_path=high_risk_for_file_idx(i),
                    allow_multiple_audit_companies=False,
                )
                persist_report_result(
                    source_name=names[i],
                    sheet_name=sheet,
                    locale=locale,
                    mode="ai",
                    content_sha256=content_fingerprint(df, names[i]),
                    observation_rows=list(
                        (audit_payload or {})
                        .get("audit_observations", {})
                        .get("rows", [])
                    ),
                    audit_payload=audit_payload or {},
                )
                pages.append((title, html_i))
            mail_url = request.build_absolute_uri("/api/send-obs-email")
            plan_url = request.build_absolute_uri("/api/parse-audit-plan-pptx")
            pages_live = [
                (t, inject_web_mail_api(h, mail_url, plan_url)) for t, h in pages
            ]
            shell = build_multi_dashboard_shell(
                pages_live,
                locale=locale,
                mail_api_script=(
                    f"window.__AI_EXCEL_MAIL_API__={json.dumps(mail_url)}; "
                    f"window.__AI_EXCEL_PLAN_PARSE_URL__={json.dumps(plan_url)};"
                ),
            )
            return html_no_cache_response(shell)

        df = dfs[0]
        source_name = names[0]
        if mode == "exact" and os.path.exists(REFERENCE_DASHBOARD):
            html_out = render_from_reference(df, REFERENCE_DASHBOARD)
            return html_no_cache_response(html_out)

        try:
            html_out, audit_payload = generate_finance_report(
                df,
                source_name=source_name,
                sheet_name=sheet,
                locale=locale,
                attached_deck_path=deck_for_file_idx(0),
                attached_high_risk_deck_path=high_risk_for_file_idx(0),
                allow_multiple_audit_companies=False,
            )
        except (ValueError, FileNotFoundError) as exc:
            return HttpResponse(html.escape(str(exc)), status=400)
        persist_report_result(
            source_name=source_name,
            sheet_name=sheet,
            locale=locale,
            mode="ai",
            content_sha256=content_fingerprint(df, source_name),
            observation_rows=list(
                (audit_payload or {}).get("audit_observations", {}).get("rows", [])
            ),
            audit_payload=audit_payload or {},
        )
        mail_url = request.build_absolute_uri("/api/send-obs-email")
        plan_url = request.build_absolute_uri("/api/parse-audit-plan-pptx")
        return html_no_cache_response(inject_web_mail_api(html_out, mail_url, plan_url))


def version_payload(module_file: str) -> dict[str, str]:
    return {"report_version": REPORT_VERSION, "module_file": module_file}


def export_zip_bytes(html_out: str, audit_payload: dict[str, Any], df) -> bytes:
    return create_export_zip(html_out, audit_payload, df)


def export_pptx_bytes(df, audit_payload: dict[str, Any]) -> bytes | None:
    return build_summary_pptx(df, audit_payload)


def dataframe_fingerprint(df, source_name: str) -> str:
    return content_fingerprint(df, source_name)
