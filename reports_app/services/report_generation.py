from __future__ import annotations

import html
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from django.http import HttpResponse
from django.utils.text import slugify

from ai_excel_dashboard import (
    _MAIL_API_MARKER,
    _PLAN_PARSE_API_MARKER,
    _REVIEWS_API_MARKER,
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


def inject_dashboard_reviews_api(html_out: str, reviews_url: str | None) -> str:
    snippet = f"window.__AI_EXCEL_REVIEWS_API__={json.dumps(reviews_url)};"
    try:
        if _REVIEWS_API_MARKER in html_out:
            return html_out.replace(_REVIEWS_API_MARKER, snippet)
        import re

        if re.search(r"window\.__AI_EXCEL_REVIEWS_API__=", html_out):
            return re.sub(
                r"window\.__AI_EXCEL_REVIEWS_API__=.+?;",
                snippet,
                html_out,
                count=1,
            )
        return html_out
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


def _save_uploaded_decks_to_media(
    request,
    report_id: str,
    *,
    field_prefix: str,
    file_stem_prefix: str,
    media_subdir: str = "decks",
) -> list[str]:
    from django.conf import settings as _settings

    deck_up = request.FILES.get(f"{field_prefix}1")
    if not deck_up:
        return []

    media_dir = Path(_settings.MEDIA_ROOT) / media_subdir / report_id
    media_dir.mkdir(parents=True, exist_ok=True)
    safe_ext = Path(deck_up.name).suffix.lower()
    fname = f"{file_stem_prefix}1{safe_ext}"
    dest = media_dir / fname
    with dest.open("wb") as fh:
        for chunk in deck_up.chunks():
            fh.write(chunk)
    return [f"{media_subdir}/{report_id}/{fname}"]


def _abs_media_paths(relative_paths: list[str] | None) -> list[str]:
    from django.conf import settings as _settings

    root = Path(_settings.MEDIA_ROOT)
    return [
        str(root / rel)
        for rel in (relative_paths or [])
        if (root / rel).is_file()
    ]


def _attached_deck_for_index(
    deck_paths: list[str], file_idx: int, n_files: int
) -> str | None:
    return resolve_attached_deck_for_workbook_index(deck_paths, file_idx, n_files)


def _first_attached_deck_path(relative_paths: list[str] | None) -> str | None:
    abs_paths = _abs_media_paths(relative_paths)
    return abs_paths[0] if abs_paths else None


def report_locale_for_dashboard(dashboard, request) -> str:
    """Locale for generated report HTML (iframe content). AI dashboards are English-only."""
    if getattr(dashboard, "template_type", None) == "ai":
        return "en"
    return normalize_locale(request.session.get("ui_lang", "ar"))


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
            df = read_input_file(path, sheet_name=sheet, locale=locale)
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


def process_uploads_to_html_and_meta(request) -> tuple[str, str, list[str]]:
    """
    Process uploaded Excel files and return (html_out, report_id, source_names).

    Raises ValueError with a user-facing message on bad input.
    The report is also persisted to the DB via persist_report_result.
    """
    locale = normalize_locale(request.POST.get("lang"))
    mode = (request.POST.get("mode") or "ai").strip().lower()
    sheet = (request.POST.get("sheet") or "").strip() or None
    uploads = excel_uploads_from_request(request)

    if not uploads:
        raise ValueError(tr(locale, "web_err_no_file"))
    if len(uploads) > AUDIT_BUNDLE_MAX_FILES:
        raise ValueError(tr(locale, "web_err_too_many_files", max=AUDIT_BUNDLE_MAX_FILES))

    mail_url = request.build_absolute_uri("/api/send-obs-email")
    plan_url = request.build_absolute_uri("/api/parse-audit-plan-pptx")

    with tempfile.TemporaryDirectory() as tmp_dir:
        dfs = []
        names = []
        for up in uploads:
            path = _persist_upload(up, tmp_dir)
            df = read_input_file(path, sheet_name=sheet, locale=locale)
            if df.empty:
                raise ValueError(tr(locale, "web_err_empty"))
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

        first_report_id = None

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
                if first_report_id is None:
                    first_report_id = (audit_payload or {}).get("report_id") or str(uuid.uuid4())
                persist_report_result(
                    source_name=names[i],
                    sheet_name=sheet,
                    locale=locale,
                    mode="ai",
                    content_sha256=content_fingerprint(df, names[i]),
                    observation_rows=list(
                        (audit_payload or {}).get("audit_observations", {}).get("rows", [])
                    ),
                    audit_payload=audit_payload or {},
                )
                pages.append((title, html_i))

            pages_live = [(t, inject_web_mail_api(h, mail_url, plan_url)) for t, h in pages]
            shell = build_multi_dashboard_shell(
                pages_live,
                locale=locale,
                mail_api_script=(
                    f"window.__AI_EXCEL_MAIL_API__={json.dumps(mail_url)}; "
                    f"window.__AI_EXCEL_PLAN_PARSE_URL__={json.dumps(plan_url)};"
                ),
            )
            return shell, first_report_id or str(uuid.uuid4()), names

        df = dfs[0]
        source_name = names[0]

        if mode == "exact" and os.path.exists(REFERENCE_DASHBOARD):
            html_out = render_from_reference(df, REFERENCE_DASHBOARD)
            report_id = f"exact-{str(uuid.uuid4())[:8]}"
            return html_out, report_id, names

        html_out, audit_payload = generate_finance_report(
            df,
            source_name=source_name,
            sheet_name=sheet,
            locale=locale,
            attached_deck_path=deck_for_file_idx(0),
            attached_high_risk_deck_path=high_risk_for_file_idx(0),
            allow_multiple_audit_companies=False,
        )
        first_report_id = (audit_payload or {}).get("report_id") or str(uuid.uuid4())
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
        return inject_web_mail_api(html_out, mail_url, plan_url), first_report_id, names


# ── New architecture: store-only upload + on-demand generation ────────


def store_upload_to_db(
    request,
    dashboard_name: str,
    icon: str,
    template_type: str = "ai",
    description: str = "",
) -> "Dashboard":
    """
    Read uploaded Excel files (file1 required; file2-4 optional), store ALL
    row data in the DB as JSON, persist audit observation records, and create
    a Dashboard record.

    Deck/plan files (deck1, high_risk_deck1) are saved to media/decks/<report_id>/
    and embedded in the dashboard HTML when it is generated on view.

    Returns the created Dashboard instance.
    Raises ValueError with a user-facing message on bad input.
    """
    import pandas as pd
    from django.conf import settings as _settings
    from audit_app.models import Dashboard, ICON_CHOICES, UploadSession

    ui_locale = normalize_locale(request.session.get("ui_lang", "ar"))
    sheet = None
    uploads = excel_uploads_from_request(request)

    if not uploads:
        raise ValueError(tr(ui_locale, "web_err_no_file"))

    # Validate icon choice
    valid_icons = {v for v, _ in ICON_CHOICES}
    if icon not in valid_icons:
        icon = "bi-bar-chart-line-fill"

    with tempfile.TemporaryDirectory() as tmp_dir:
        # ── Read all Excel files ──────────────────────────────────────
        file_entries = []   # list of {"columns":[…], "data":[…], "source_name":"…"}
        all_names = []
        primary_df = None
        primary_name = None
        primary_sha256 = None
        primary_audit_payload: dict = {}

        for up in uploads:
            path = _persist_upload(up, tmp_dir)
            df = read_input_file(path, sheet_name=sheet, locale=ui_locale)
            if isinstance(df, dict):
                first_key = next(iter(df.keys()))
                df = df[first_key]
            df = df.dropna(how="all").dropna(axis=1, how="all")
            if df.empty:
                continue

            entry = json.loads(
                df.to_json(orient="split", force_ascii=False, default_handler=str)
            )
            entry["source_name"] = up.name
            file_entries.append(entry)
            all_names.append(up.name)

            if primary_df is None:
                primary_df = df
                primary_name = up.name
                primary_sha256 = content_fingerprint(df, up.name)

        if not file_entries or primary_df is None:
            raise ValueError(tr(ui_locale, "web_err_empty"))

        # ── Persist audit observation records (primary file only) ─────
        _, audit_payload = generate_finance_report(
            primary_df,
            source_name=primary_name,
            sheet_name=sheet,
            locale=ui_locale,
            allow_multiple_audit_companies=False,
        )
        primary_audit_payload = audit_payload or {}

        session = persist_report_result(
            source_name=primary_name,
            sheet_name=sheet,
            locale=ui_locale,
            mode=template_type,
            content_sha256=primary_sha256,
            observation_rows=list(
                primary_audit_payload.get("audit_observations", {}).get("rows", [])
            ),
            audit_payload=primary_audit_payload,
        )

        # Store multi-file raw data (list format for ≥2 files, dict for 1)
        if isinstance(session, UploadSession):
            if len(file_entries) == 1:
                raw_json = json.dumps(file_entries[0], ensure_ascii=False)
            else:
                raw_json = json.dumps(file_entries, ensure_ascii=False)
            session.raw_data_json = raw_json
            session.save(update_fields=["raw_data_json"])

        report_id = primary_audit_payload.get("report_id") or str(uuid.uuid4())

        # ── Save deck/plan files to media ────────────────────────────
        deck_paths = _save_uploaded_decks_to_media(
            request, report_id, field_prefix="deck", file_stem_prefix="deck"
        )
        high_risk_paths = _save_uploaded_decks_to_media(
            request,
            report_id,
            field_prefix="high_risk_deck",
            file_stem_prefix="high_risk_deck",
        )

        source_files_info = {
            "excel": all_names,
            "decks": deck_paths,
            "high_risk_decks": high_risk_paths,
        }

        dashboard = Dashboard.objects.create(
            name=dashboard_name,
            description=description,
            icon=icon,
            template_type=template_type,
            report_id=report_id,
            html_file="",  # generated on first view
            source_files=source_files_info,
            created_by=request.user if request.user.is_authenticated else None,
            upload_session=session if isinstance(session, UploadSession) else None,
        )
        return dashboard


def generate_from_db_data(dashboard, request, locale: str | None = None) -> str:
    """
    Generate the full dashboard HTML from the raw_data_json stored in the
    associated UploadSession.

    *locale* defaults to the current session language so the displayed chart
    labels/titles match the UI language the user has selected.  Pass an
    explicit value to force a specific locale.

    Returns the HTML string.  Raises ValueError if no data is stored.
    """
    import pandas as pd

    session = dashboard.upload_session
    if not session or not session.raw_data_json:
        raise ValueError("No stored data for this dashboard.")

    # AI dashboards are always English; others follow the UI language.
    if getattr(dashboard, "template_type", None) == "ai":
        locale = "en"
    elif locale is None:
        locale = request.session.get("ui_lang", session.locale or "ar")
    locale = normalize_locale(locale)

    raw = json.loads(session.raw_data_json)

    mail_url = request.build_absolute_uri("/api/send-obs-email")
    plan_url = request.build_absolute_uri("/api/parse-audit-plan-pptx")

    source_files = dashboard.source_files or {}
    if not isinstance(source_files, dict):
        source_files = {}
    deck_rel = source_files.get("decks") or []
    high_risk_rel = source_files.get("high_risk_decks") or []
    deck_paths_abs = _abs_media_paths(deck_rel)
    high_risk_paths_abs = _abs_media_paths(high_risk_rel)

    # Support both single-file dict and multi-file list formats
    if isinstance(raw, list):
        # Multi-file: each entry = {"columns": [...], "data": [...], "source_name": "..."}
        entries = raw
    else:
        # Single-file dict (legacy or new single upload)
        entries = [dict(raw, source_name=raw.get("source_name", session.source_name))]

    if len(entries) == 1:
        e = entries[0]
        df = pd.DataFrame(e["data"], columns=e["columns"])
        source = e.get("source_name", session.source_name)
        html_out, _ = generate_finance_report(
            df,
            source_name=source,
            sheet_name=session.sheet_name or None,
            locale=locale,
            attached_deck_path=_first_attached_deck_path(deck_rel),
            attached_high_risk_deck_path=_first_attached_deck_path(high_risk_rel),
            allow_multiple_audit_companies=False,
        )
    else:
        # Multi-file: build tabs
        tabs = []
        n_entries = len(entries)
        for i, e in enumerate(entries):
            df = pd.DataFrame(e["data"], columns=e["columns"])
            source = e.get("source_name", "file")
            tab_html, _ = generate_finance_report(
                df,
                source_name=source,
                sheet_name=session.sheet_name or None,
                locale=locale,
                attached_deck_path=_attached_deck_for_index(
                    deck_paths_abs, i, n_entries
                ),
                attached_high_risk_deck_path=_attached_deck_for_index(
                    high_risk_paths_abs, i, n_entries
                ),
                allow_multiple_audit_companies=False,
            )
            title = workbook_dashboard_tab_title(df, source, locale)
            tabs.append((tab_html, title))

        html_out = build_multi_dashboard_shell(
            [(h, t, None, None) for h, t in tabs],
            locale=locale,
            mail_api_url=mail_url,
            plan_parse_api_url=plan_url,
        )

    result = inject_dashboard_reviews_api(
        inject_web_mail_api(html_out, mail_url, plan_url),
        request.build_absolute_uri(f"/api/dashboards/{dashboard.pk}/reviews/"),
    )

    # Fix: ensure Plotly SVG overflow is visible so axis labels aren't clipped
    overflow_fix = (
        "<style>"
        ".js-plotly-plot,.js-plotly-plot .plotly{"
        "overflow:visible!important;}"
        ".js-plotly-plot .main-svg,.js-plotly-plot .main-svg>g{"
        "overflow:visible!important;}"
        "</style>"
    )
    if "</head>" in result:
        result = result.replace("</head>", overflow_fix + "</head>", 1)
    else:
        result = overflow_fix + result

    return result
