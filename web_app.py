#!/usr/bin/env python3
"""
Upload Excel/CSV file and generate dashboard HTML report.

Run:
    python web_app.py
    .\\scripts\\run_web.ps1
Then open:
    http://127.0.0.1:5000

See START_HERE.md and docs/ARCHITECTURE.md.
"""

from __future__ import annotations

import base64
import html
import json
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, make_response, redirect, request, url_for
from werkzeug.utils import secure_filename

from ai_excel_dashboard import (
    AUDIT_BUNDLE_MAX_FILES,
    REPORT_VERSION,
    _MAIL_API_MARKER,
    _PLAN_PARSE_API_MARKER,
    _valid_obs_email,
    build_multi_dashboard_shell,
    content_fingerprint,
    generate_finance_report,
    load_smtp_config,
    parse_audit_plan_pptx_bytes,
    resolve_attached_deck_for_workbook_index,
    send_audit_observation_email_smtp,
    workbook_dashboard_tab_title,
)
import ai_excel_dashboard as _ai_excel_dashboard_mod
from dashboard_locale import normalize_locale, tr
from data_io import read_input_file
from exact_dashboard import render_from_reference
from export_bundle import build_summary_pptx, create_export_zip


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB


@app.after_request
def _add_dashboard_version_header(response):
    response.headers["X-Dashboard-Version"] = REPORT_VERSION
    return response


@app.route("/api/version", methods=["GET"])
def api_version():
    """Confirm which code build the server is running (for deploy checks)."""
    return jsonify(
        {
            "report_version": REPORT_VERSION,
            "module_file": str(getattr(_ai_excel_dashboard_mod, "__file__", "")),
        }
    )


def _inject_web_mail_api(html_out: str) -> str:
    """Inject same-origin API URLs for Send email and Audit Plan PPTX upload."""
    try:
        mail_url = url_for("api_send_obs_email", _external=True)
        plan_url = url_for("api_parse_audit_plan_pptx", _external=True)
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


def _html_no_cache_response(html: str):
    """Avoid stale dashboard JS when users re-run Analyze (browser disk cache)."""
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/api/send-obs-email", methods=["POST", "OPTIONS"])
def api_send_obs_email():
    """Send observation email via smtp_config.json (used by dashboard Send email button)."""
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        resp = jsonify({"ok": False, "error": "bad_json"})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp, 400
    to_addr = str(data.get("to", "")).strip()
    observation = str(data.get("observation", "")).strip()
    if not _valid_obs_email(to_addr):
        resp = jsonify({"ok": False, "error": "bad_email"})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp, 400
    if not observation or len(observation) > 8000:
        resp = jsonify({"ok": False, "error": "bad_observation"})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp, 400
    cfg = load_smtp_config()
    if not cfg:
        resp = jsonify({"ok": False, "error": "smtp_not_configured"})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp, 503
    try:
        send_audit_observation_email_smtp(
            cfg, to_addr=to_addr, observation=observation
        )
    except Exception as exc:
        resp = jsonify({"ok": False, "error": str(exc)[:500]})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp, 500
    resp = jsonify({"ok": True})
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.route("/api/parse-audit-plan-pptx", methods=["POST", "OPTIONS"])
def api_parse_audit_plan_pptx():
    """Parse .pptx audit plan table server-side (avoids fragile browser ZIP/DOM parsing)."""
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        resp = jsonify({"ok": False, "error": "bad_json", "rows": []})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp, 400
    b64 = str(data.get("pptx_b64", "")).strip()
    if not b64:
        resp = jsonify({"ok": False, "error": "missing_pptx_b64", "rows": []})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp, 400
    try:
        raw_pptx = base64.b64decode(b64, validate=False)
    except Exception:
        resp = jsonify({"ok": False, "error": "bad_b64", "rows": []})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp, 400
    rows, err = parse_audit_plan_pptx_bytes(raw_pptx)
    if err:
        resp = jsonify({"ok": False, "error": err, "rows": []})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp, 400
    resp = jsonify({"ok": True, "rows": rows})
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


REFERENCE_DASHBOARD = os.environ.get("EXACT_DASHBOARD_TEMPLATE", "").strip()
AUDIT_DIR = os.path.join(os.path.dirname(__file__), "audit_logs")


def _nonempty_uploads(file_list) -> list:
    out = []
    for f in file_list or []:
        if f and getattr(f, "filename", None) and str(f.filename).strip():
            out.append(f)
    return out


def _excel_uploads_from_request(req) -> list:
    """Prefer separate file1..file4 fields (reliable multi-file UX); fall back to files[] / file."""
    slot: list = []
    for key in ("file1", "file2", "file3", "file4"):
        f = req.files.get(key)
        if f and f.filename and str(f.filename).strip():
            slot.append(f)
    if slot:
        return slot[:AUDIT_BUNDLE_MAX_FILES]
    uploads = _nonempty_uploads(req.files.getlist("files"))
    if not uploads:
        legacy = req.files.get("file")
        if legacy and legacy.filename and str(legacy.filename).strip():
            uploads = [legacy]
    return uploads[:AUDIT_BUNDLE_MAX_FILES]


def _deck_uploads_from_request(req) -> list:
    slot: list = []
    for key in ("deck1", "deck2", "deck3", "deck4"):
        f = req.files.get(key)
        if f and f.filename and str(f.filename).strip():
            slot.append(f)
    if slot:
        return slot[:AUDIT_BUNDLE_MAX_FILES]
    decks = _nonempty_uploads(req.files.getlist("decks"))
    if not decks:
        legacy = req.files.get("deck")
        if legacy and legacy.filename and str(legacy.filename).strip():
            decks = [legacy]
    return decks[:AUDIT_BUNDLE_MAX_FILES]


def _prepare_dataframe_from_tmp(
    tmp_path: str, sheet: str | None, report_locale: str
):
    df = read_input_file(tmp_path, sheet_name=sheet, locale=report_locale)
    if isinstance(df, dict):
        first_key = next(iter(df.keys()))
        df = df[first_key]
    attrs_bak = dict(getattr(df, "attrs", {}) or {})
    df = df.dropna(how="all").dropna(axis=1, how="all")
    if attrs_bak:
        df.attrs = getattr(df, "attrs", {})
        df.attrs.update(attrs_bak)
    return df


def _save_deck_uploads(deck_uploads, tmp_dir: str, report_locale: str) -> list[str]:
    paths: list[str] = []
    for deck_upload in deck_uploads:
        if not deck_upload or not deck_upload.filename:
            continue
        dext = Path(deck_upload.filename).suffix.lower()
        if dext not in {".pptx", ".ppt", ".pdf"}:
            raise ValueError(tr(report_locale, "web_err_bad_deck"))
        dname = secure_filename(deck_upload.filename)
        if not dname:
            dname = f"deck{len(paths)}{dext or '.pptx'}"
        p = os.path.join(tmp_dir, dname)
        deck_upload.save(p)
        paths.append(p)
    return paths


def _save_high_risk_deck_slot_paths(
    req, tmp_dir: str, report_locale: str
) -> list[str | None] | None:
    """Optional high-risk decks (English reports only), aligned to workbook rows."""
    if normalize_locale(report_locale) != "en":
        return None
    out: list[str | None] = []
    seen_any = False
    for ki, key in enumerate(
        ("high_risk_deck1", "high_risk_deck2", "high_risk_deck3", "high_risk_deck4")
    ):
        f = req.files.get(key)
        if not f or not f.filename or not str(f.filename).strip():
            legacy = req.files.get("high_risk_deck") if ki == 0 else None
            if legacy and legacy.filename and str(legacy.filename).strip():
                f = legacy
            else:
                out.append(None)
                continue
        seen_any = True
        dext = Path(f.filename).suffix.lower()
        if dext not in {".pptx", ".ppt", ".pdf"}:
            raise ValueError(tr(report_locale, "web_err_bad_deck"))
        dname = secure_filename(f.filename) or f"high-risk-deck{ki}{dext or '.pptx'}"
        p = os.path.join(tmp_dir, dname)
        f.save(p)
        out.append(p)
    return out if seen_any else None


def _save_deck_slot_paths(req, tmp_dir: str, report_locale: str) -> list[str | None] | None:
    """If any deck1..deck4 was chosen, return four entries (path or None) aligned to workbook rows."""
    out: list[str | None] = []
    seen_any = False
    for ki, key in enumerate(("deck1", "deck2", "deck3", "deck4")):
        f = req.files.get(key)
        if not f or not f.filename or not str(f.filename).strip():
            out.append(None)
            continue
        seen_any = True
        dext = Path(f.filename).suffix.lower()
        if dext not in {".pptx", ".ppt", ".pdf"}:
            raise ValueError(tr(report_locale, "web_err_bad_deck"))
        dname = secure_filename(f.filename) or f"deck{ki}{dext or '.pptx'}"
        p = os.path.join(tmp_dir, dname)
        f.save(p)
        out.append(p)
    return out if seen_any else None


def _save_audit(audit_payload: dict) -> None:
    os.makedirs(AUDIT_DIR, exist_ok=True)
    audit_file = os.path.join(AUDIT_DIR, f"{audit_payload['report_id']}.json")
    with open(audit_file, "w", encoding="utf-8") as f:
        json.dump(audit_payload, f, ensure_ascii=False, indent=2)


def _zip_download(zip_bytes: bytes, download_name: str):
    resp = make_response(zip_bytes)
    resp.headers["Content-Type"] = "application/zip"
    resp.headers["Content-Disposition"] = f'attachment; filename="{download_name}"'
    return resp


def _respond_ai_report(
    df,
    source_name: str,
    sheet_name: str | None,
    *,
    export_bundle: bool,
    download_html: bool = False,
    download_pptx: bool = False,
    locale: str = "en",
    attached_deck_path: str | None = None,
    embedded_decks_by_company_path: dict[str, str] | None = None,
    attached_high_risk_deck_path: str | None = None,
    allow_multiple_audit_companies: bool = False,
):
    html_out, audit_payload = generate_finance_report(
        df,
        source_name=source_name,
        sheet_name=sheet_name,
        locale=locale,
        attached_deck_path=attached_deck_path,
        embedded_decks_by_company_path=embedded_decks_by_company_path,
        attached_high_risk_deck_path=attached_high_risk_deck_path,
        allow_multiple_audit_companies=allow_multiple_audit_companies,
    )
    _save_audit(audit_payload)
    if export_bundle:
        zip_bytes = create_export_zip(html_out, audit_payload, df)
        stem = secure_filename(Path(source_name).stem) or "export"
        return _zip_download(zip_bytes, f"{stem}_{audit_payload['report_id'][:8]}.zip")
    if download_html:
        stem = secure_filename(Path(source_name).stem) or "report"
        resp = make_response(html_out)
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        resp.headers["Content-Disposition"] = (
            f'attachment; filename="{stem}_report.html"'
        )
        return resp
    if download_pptx:
        pptx_bytes = build_summary_pptx(df, audit_payload)
        if not pptx_bytes:
            return tr(locale, "web_err_pptx"), 500
        stem = secure_filename(Path(source_name).stem) or "report"
        resp = make_response(pptx_bytes)
        resp.headers[
            "Content-Type"
        ] = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        resp.headers["Content-Disposition"] = (
            f'attachment; filename="{stem}_insight-summary.pptx"'
        )
        return resp
    return _html_no_cache_response(_inject_web_mail_api(html_out))


def upload_form_html(locale: str | None = None) -> str:
    loc = normalize_locale(locale)
    lang = "ar" if loc == "ar" else "en"
    dir_ = "rtl" if loc == "ar" else "ltr"
    sel_en = ' selected="selected"' if loc != "ar" else ""
    sel_ar = ' selected="selected"' if loc == "ar" else ""
    return f"""<!doctype html>
<html lang="{lang}" dir="{dir_}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(tr(loc, "web_title"))}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Arabic:wght@400;600;700&display=swap" rel="stylesheet" />
  <style>
    body{{margin:0;font-family:"Noto Sans Arabic","Segoe UI",Tahoma,Arial,sans-serif;background:#f0f2f5;color:#1a1a2e}}
    .wrap{{max-width:780px;margin:50px auto;padding:24px}}
    .card{{background:#fff;border:1px solid #dde1ea;border-radius:14px;padding:24px;box-shadow:0 6px 20px rgba(0,0,0,.08)}}
    h1{{margin:0 0 8px;color:#007a38}}
    p{{color:#5b6270}}
    .row{{margin-top:14px}}
    input,button{{font-size:15px}}
    input[type=file],input[type=text]{{width:100%;padding:10px;border:1px solid #ccd3df;border-radius:8px}}
    .btn-row{{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}}
    button,.btn{{border:none;padding:11px 18px;border-radius:10px;font-weight:700;cursor:pointer;font-size:15px}}
    .btn-primary{{background:#00B050;color:#fff}}
    .btn-primary:hover{{background:#009247}}
    .btn-secondary{{background:#fff;color:#1a1a2e;border:2px solid #007a38}}
    .btn-secondary:hover{{background:#e8f5ee}}
    .hint{{font-size:13px;color:#64748b;margin-top:12px;line-height:1.45}}
    .build-tag{{font-size:12px;color:#94a3b8;margin-top:16px}}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>{html.escape(tr(loc, "web_h1"))}</h1>
      <p>{html.escape(tr(loc, "web_intro"))}</p>
      <p class="build-tag">Build: {html.escape(REPORT_VERSION)}</p>
      <form action="/analyze" method="post" enctype="multipart/form-data">
        <div class="row">
          <label><strong>{html.escape(tr(loc, "web_file_label"))}</strong></label>
          <div class="hint" style="margin-top:4px;margin-bottom:8px">{html.escape(tr(loc, "web_file_slots_intro"))}</div>
          <label style="display:block;margin-top:10px;font-size:14px;color:#334155">{html.escape(tr(loc, "web_workbook_slot", n=1))} ({html.escape(tr(loc, "web_workbook_required"))})</label>
          <input type="file" name="file1" accept=".xlsx,.xls,.xlsm,.csv" style="margin-top:4px" />
          <label style="display:block;margin-top:12px;font-size:14px;color:#334155">{html.escape(tr(loc, "web_workbook_slot", n=2))} ({html.escape(tr(loc, "web_workbook_optional"))})</label>
          <input type="file" name="file2" accept=".xlsx,.xls,.xlsm,.csv" style="margin-top:4px" />
          <label style="display:block;margin-top:12px;font-size:14px;color:#334155">{html.escape(tr(loc, "web_workbook_slot", n=3))} ({html.escape(tr(loc, "web_workbook_optional"))})</label>
          <input type="file" name="file3" accept=".xlsx,.xls,.xlsm,.csv" style="margin-top:4px" />
          <label style="display:block;margin-top:12px;font-size:14px;color:#334155">{html.escape(tr(loc, "web_workbook_slot", n=4))} ({html.escape(tr(loc, "web_workbook_optional"))})</label>
          <input type="file" name="file4" accept=".xlsx,.xls,.xlsm,.csv" style="margin-top:4px" />
        </div>
        <div class="row">
          <label><strong>{html.escape(tr(loc, "web_sheet_label"))}</strong></label>
          <input type="text" name="sheet" placeholder="{html.escape(tr(loc, "web_sheet_ph"))}" />
        </div>
        <div class="row">
          <label><strong>{html.escape(tr(loc, "web_deck_label_multi"))}</strong></label>
          <div class="hint" style="margin-top:4px;margin-bottom:8px">{html.escape(tr(loc, "web_deck_hint_multi"))}</div>
          <label style="display:block;margin-top:4px;font-size:14px;color:#334155">{html.escape(tr(loc, "web_deck_slot", n=1))}</label>
          <input type="file" name="deck1" accept=".pptx,.ppt,.pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.ms-powerpoint,application/pdf" style="margin-top:4px" />
          <label style="display:block;margin-top:12px;font-size:14px;color:#334155">{html.escape(tr(loc, "web_deck_slot", n=2))}</label>
          <input type="file" name="deck2" accept=".pptx,.ppt,.pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.ms-powerpoint,application/pdf" style="margin-top:4px" />
          <label style="display:block;margin-top:12px;font-size:14px;color:#334155">{html.escape(tr(loc, "web_deck_slot", n=3))}</label>
          <input type="file" name="deck3" accept=".pptx,.ppt,.pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.ms-powerpoint,application/pdf" style="margin-top:4px" />
          <label style="display:block;margin-top:12px;font-size:14px;color:#334155">{html.escape(tr(loc, "web_deck_slot", n=4))}</label>
          <input type="file" name="deck4" accept=".pptx,.ppt,.pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.ms-powerpoint,application/pdf" style="margin-top:4px" />
          <div class="hint" style="margin-top:10px">{html.escape(tr(loc, "web_deck_hint"))}</div>
        </div>
        {(
            '<div class="row" id="web-high-risk-deck-row">'
            f'<label><strong>{html.escape(tr("en", "web_high_risk_deck_label"))}</strong></label>'
            f'<div class="hint" style="margin-top:4px;margin-bottom:8px">'
            f'{html.escape(tr("en", "gui_high_risk_deck_hint"))}</div>'
            + "".join(
                f'<label style="display:block;margin-top:{"4" if n == 1 else "12"}px;font-size:14px;color:#334155">'
                f'High risk deck {n}</label>'
                f'<input type="file" name="high_risk_deck{n}" accept=".pptx,.ppt,.pdf,'
                f'application/vnd.openxmlformats-officedocument.presentationml.presentation,'
                f'application/vnd.ms-powerpoint,application/pdf" style="margin-top:4px" />'
                for n in range(1, 5)
            )
            + "</div>"
        ) if loc == "en" else ""}
        <div class="row">
          <label><strong>{html.escape(tr(loc, "web_mode_label"))}</strong></label>
          <select name="mode" style="width:100%;padding:10px;border:1px solid #ccd3df;border-radius:8px">
            <option value="ai" selected>{html.escape(tr(loc, "web_mode_ai"))}</option>
            <option value="exact">{html.escape(tr(loc, "web_mode_exact"))}</option>
          </select>
        </div>
        <div class="row">
          <label><strong>{html.escape(tr(loc, "web_lang_label"))}</strong></label>
          <select name="lang" style="width:100%;padding:10px;border:1px solid #ccd3df;border-radius:8px">
            <option value="en"{sel_en}>{html.escape(tr(loc, "web_lang_en"))}</option>
            <option value="ar"{sel_ar}>{html.escape(tr(loc, "web_lang_ar"))}</option>
          </select>
        </div>
        <div class="row">
          <strong>{html.escape(tr(loc, "web_next_label"))}</strong>
          <div class="btn-row">
            <button type="submit" class="btn btn-primary" name="submit_action" value="view">{html.escape(tr(loc, "web_btn_view"))}</button>
          </div>
        </div>
        <div class="hint">{html.escape(tr(loc, "web_hint"))}</div>
      </form>
    </div>
  </div>
</body>
</html>
"""


@app.get("/")
def index() -> str:
    return upload_form_html(request.args.get("lang"))


@app.get("/analyze")
def analyze_get():
    return redirect(url_for("index"))


@app.post("/analyze")
def analyze() -> tuple[str, int] | str:
    report_locale = normalize_locale(request.form.get("lang"))
    uploads = _excel_uploads_from_request(request)
    if not uploads:
        return tr(report_locale, "web_err_no_file"), 400
    if len(uploads) > AUDIT_BUNDLE_MAX_FILES:
        return (
            tr(
                report_locale,
                "web_err_too_many_files",
                max=AUDIT_BUNDLE_MAX_FILES,
            ),
            400,
        )

    sheet = (request.form.get("sheet") or "").strip() or None

    mode = (request.form.get("mode") or "ai").strip().lower()
    action = (request.form.get("submit_action") or "view").strip().lower()
    if action != "view":
        action = "view"
    export_bundle = False
    download_html = False
    download_pptx = False

    nf = len(uploads)
    if nf > 1 and mode != "ai":
        return tr(report_locale, "web_err_multi_mode"), 400

    with tempfile.TemporaryDirectory() as tmp_dir:
        dfs: list = []
        names: list[str] = []
        for up in uploads:
            ext = Path(up.filename).suffix.lower()
            if ext not in {".xlsx", ".xls", ".xlsm", ".csv"}:
                return tr(report_locale, "web_err_bad_type"), 400
            raw_name = secure_filename(up.filename) or f"upload_{len(dfs)}{ext}"
            tmp_path = os.path.join(tmp_dir, raw_name)
            up.save(tmp_path)
            df = _prepare_dataframe_from_tmp(tmp_path, sheet, report_locale)
            if df.empty:
                return tr(report_locale, "web_err_empty"), 400
            dfs.append(df)
            names.append(up.filename)

        try:
            deck_slots = _save_deck_slot_paths(request, tmp_dir, report_locale)
        except ValueError as exc:
            return html.escape(str(exc)), 400
        try:
            high_risk_deck_slots = _save_high_risk_deck_slot_paths(
                request, tmp_dir, report_locale
            )
        except ValueError as exc:
            return html.escape(str(exc)), 400

        legacy_deck_saved: list[str] = []
        if deck_slots is None:
            try:
                legacy_deck_saved = _save_deck_uploads(
                    _deck_uploads_from_request(request),
                    tmp_dir,
                    report_locale,
                )
            except ValueError as exc:
                return html.escape(str(exc)), 400

        def deck_for_file_idx(i: int) -> str | None:
            if deck_slots is not None:
                nn = [p for p in deck_slots if p]
                if len(nn) == 1:
                    return nn[0]
                if i < len(deck_slots) and deck_slots[i]:
                    return deck_slots[i]
                return None
            if not legacy_deck_saved:
                return None
            if len(legacy_deck_saved) == 1:
                return legacy_deck_saved[0]
            if len(legacy_deck_saved) == nf:
                return legacy_deck_saved[i]
            return None

        def high_risk_paths_list() -> list[str]:
            if high_risk_deck_slots is None:
                return []
            return [p for p in high_risk_deck_slots if p]

        def high_risk_for_file_idx(i: int) -> str | None:
            return resolve_attached_deck_for_workbook_index(
                high_risk_paths_list(), i, nf
            )

        hr_paths = high_risk_paths_list()
        nhr = len(hr_paths)
        if nhr > 1 and nhr != nf:
            return tr(report_locale, "web_err_deck_count"), 400

        if mode == "ai" and nf > 1:
            pages: list[tuple[str, str]] = []
            for i in range(nf):
                stem = secure_filename(Path(names[i]).stem) or f"file{i + 1}"
                tab_title = workbook_dashboard_tab_title(dfs[i], stem)
                try:
                    html_i, audit_i = generate_finance_report(
                        dfs[i],
                        source_name=names[i],
                        sheet_name=sheet,
                        locale=report_locale,
                        attached_deck_path=deck_for_file_idx(i),
                        attached_high_risk_deck_path=high_risk_for_file_idx(i),
                        allow_multiple_audit_companies=False,
                    )
                except (ValueError, FileNotFoundError) as exc:
                    return html.escape(str(exc)), 400
                _save_audit(audit_i)
                pages.append((tab_title, html_i))
            mail_url = url_for("api_send_obs_email", _external=True)
            plan_url = url_for("api_parse_audit_plan_pptx", _external=True)
            inject_mail = f"window.__AI_EXCEL_MAIL_API__={json.dumps(mail_url)};"
            inject_plan = f"window.__AI_EXCEL_PLAN_PARSE_URL__={json.dumps(plan_url)};"
            pages_live = [
                (
                    t,
                    h.replace(_MAIL_API_MARKER, inject_mail).replace(
                        _PLAN_PARSE_API_MARKER, inject_plan
                    ),
                )
                for t, h in pages
            ]
            return _html_no_cache_response(
                build_multi_dashboard_shell(
                    pages_live,
                    locale=report_locale,
                    mail_api_script=inject_mail + " " + inject_plan,
                )
            )

        df = dfs[0]
        source_label = names[0]
        if deck_slots is not None:
            deck_disk_path = next((p for p in deck_slots if p), None)
        else:
            deck_disk_path = legacy_deck_saved[0] if legacy_deck_saved else None

        try:
            if mode == "ai":
                return _respond_ai_report(
                    df,
                    source_label,
                    sheet,
                    export_bundle=export_bundle,
                    download_html=download_html,
                    download_pptx=download_pptx,
                    locale=report_locale,
                    attached_deck_path=deck_disk_path,
                    embedded_decks_by_company_path=None,
                    attached_high_risk_deck_path=high_risk_for_file_idx(0),
                    allow_multiple_audit_companies=False,
                )
        except (ValueError, FileNotFoundError) as exc:
            return html.escape(str(exc)), 400
        primary_name = names[0]
        if os.path.exists(REFERENCE_DASHBOARD):
            html_out = render_from_reference(df, REFERENCE_DASHBOARD)
            if download_html:
                stem = secure_filename(Path(primary_name).stem) or "report"
                resp = make_response(html_out)
                resp.headers["Content-Type"] = "text/html; charset=utf-8"
                resp.headers["Content-Disposition"] = (
                    f'attachment; filename="{stem}_exact-dashboard.html"'
                )
                return resp
            if download_pptx:
                report_id = str(uuid.uuid4())
                generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                audit_payload = {
                    "report_id": report_id,
                    "report_version": "exact-template",
                    "generated_at": generated_at,
                    "mode": "exact_template",
                    "source_name": source_label,
                    "sheet_name": sheet,
                    "rows": int(df.shape[0]),
                    "columns": int(df.shape[1]),
                    "missing_cells": int(df.isna().sum().sum()),
                    "duplicate_rows": int(df.duplicated().sum()),
                    "content_sha256": content_fingerprint(df, source_label),
                    "detected_columns": {},
                    "schema_warnings": [],
                    "triggered_anomalies": [],
                    "finance_kpis": [],
                }
                _save_audit(audit_payload)
                pptx_bytes = build_summary_pptx(df, audit_payload)
                if not pptx_bytes:
                    return tr(report_locale, "web_err_pptx"), 500
                stem = secure_filename(Path(primary_name).stem) or "report"
                resp = make_response(pptx_bytes)
                resp.headers[
                    "Content-Type"
                ] = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                resp.headers["Content-Disposition"] = (
                    f'attachment; filename="{stem}_exact-summary.pptx"'
                )
                return resp
            if export_bundle:
                report_id = str(uuid.uuid4())
                generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                audit_payload = {
                    "report_id": report_id,
                    "report_version": "exact-template",
                    "generated_at": generated_at,
                    "mode": "exact_template",
                    "source_name": source_label,
                    "sheet_name": sheet,
                    "rows": int(df.shape[0]),
                    "columns": int(df.shape[1]),
                    "missing_cells": int(df.isna().sum().sum()),
                    "duplicate_rows": int(df.duplicated().sum()),
                    "content_sha256": content_fingerprint(df, source_label),
                    "detected_columns": {},
                    "schema_warnings": [],
                    "triggered_anomalies": [],
                    "finance_kpis": [],
                }
                _save_audit(audit_payload)
                zip_bytes = create_export_zip(
                    html_out,
                    audit_payload,
                    df,
                    readme_extra="Dashboard mode: exact reference HTML template.",
                )
                stem = secure_filename(Path(primary_name).stem) or "export"
                return _zip_download(zip_bytes, f"{stem}_{report_id[:8]}.zip")
            return _html_no_cache_response(_inject_web_mail_api(html_out))
        try:
            return _respond_ai_report(
                df,
                source_label,
                sheet,
                export_bundle=export_bundle,
                download_html=download_html,
                download_pptx=download_pptx,
                locale=report_locale,
                attached_deck_path=deck_disk_path,
                embedded_decks_by_company_path=None,
                attached_high_risk_deck_path=high_risk_for_file_idx(0),
                allow_multiple_audit_companies=False,
            )
        except (ValueError, FileNotFoundError) as exc:
            return html.escape(str(exc)), 400


if __name__ == "__main__":
    mod_path = getattr(_ai_excel_dashboard_mod, "__file__", "?")
    print(f"Excel dashboard web server — {REPORT_VERSION}")
    print(f"  ai_excel_dashboard.py: {mod_path}")
    print("  Open http://127.0.0.1:5000  |  GET /api/version to verify deploy")
    app.run(host="127.0.0.1", port=5000, debug=False)
