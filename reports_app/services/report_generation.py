"""Django report orchestration: store uploads, lazy HTML generation, attachment handling."""
from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from django.utils.text import slugify

from ai_excel_dashboard import (
    _CAN_SAVE_USER_EDITS_MARKER,
    _MAIL_API_MARKER,
    _PLAN_PARSE_API_MARKER,
    _USER_EDITS_SAVE_MARKER,
    AUDIT_BUNDLE_MAX_FILES,
    REPORT_VERSION,
    build_multi_dashboard_shell,
    content_fingerprint,
    generate_finance_report,
    resolve_attached_deck_for_workbook_index,
    workbook_dashboard_tab_title,
)
from audit_app.dashboard_template_codes import (
    DEFAULT_DASHBOARD_TEMPLATE_CODE,
    TEMPLATE_CODE_CD,
    TEMPLATE_CODE_IAD,
)
from audit_app.services.persistence import persist_report_result
from dashboard_locale import normalize_locale, tr
from data_io import read_input_file

ATTACHMENT_SPECS: list[dict[str, str]] = [
    {
        "kind": "deck",
        "source_key": "decks",
        "field_prefix": "deck",
        "file_stem_prefix": "deck",
        "ui_label": "upload_deck_label",
        "ui_hint": "",
        "ui_drop": "upload_deck_drop",
        "summary_icon": "bi-file-earmark-slides",
        "zone_icon": "bi-file-slides",
        "details_id": "deckFilesDetails",
    },
    {
        "kind": "highRisk",
        "source_key": "high_risk_decks",
        "field_prefix": "high_risk_deck",
        "file_stem_prefix": "high_risk_deck",
        "ui_label": "upload_high_risk_label",
        "ui_hint": "upload_high_risk_hint",
        "ui_drop": "upload_high_risk_drop",
        "summary_icon": "bi-exclamation-triangle-fill",
        "zone_icon": "bi-file-earmark-medical",
        "details_id": "highRiskDeckDetails",
    },
    {
        "kind": "tgaViolations",
        "source_key": "tga_violations_decks",
        "field_prefix": "tga_violations_deck",
        "file_stem_prefix": "tga_violations_deck",
        "ui_label": "upload_tga_violations_label",
        "ui_hint": "upload_tga_violations_hint",
        "ui_drop": "upload_tga_violations_drop",
        "summary_icon": "bi-shield-exclamation",
        "zone_icon": "bi-file-earmark-ruled",
        "details_id": "tgaViolationsDeckDetails",
    },
    {
        "kind": "missingVehicle",
        "source_key": "missing_vehicle_decks",
        "field_prefix": "missing_vehicle_deck",
        "file_stem_prefix": "missing_vehicle_deck",
        "ui_label": "upload_missing_vehicle_label",
        "ui_hint": "upload_missing_vehicle_hint",
        "ui_drop": "upload_missing_vehicle_drop",
        "summary_icon": "bi-truck",
        "zone_icon": "bi-truck-front",
        "details_id": "missingVehicleDeckDetails",
    },
    {
        "kind": "internalAuditQuarterly",
        "source_key": "internal_audit_quarterly_decks",
        "field_prefix": "internal_audit_quarterly_deck",
        "file_stem_prefix": "internal_audit_quarterly_deck",
        "ui_label": "upload_internal_audit_quarterly_label",
        "ui_hint": "upload_internal_audit_quarterly_hint",
        "ui_drop": "upload_internal_audit_quarterly_drop",
        "summary_icon": "bi-calendar3",
        "zone_icon": "bi-file-earmark-bar-graph",
        "details_id": "internalAuditQuarterlyDeckDetails",
    },
    {
        "kind": "specialAssignment",
        "source_key": "special_assignment_decks",
        "field_prefix": "special_assignment_deck",
        "file_stem_prefix": "special_assignment_deck",
        "ui_label": "upload_special_assignment_label",
        "ui_hint": "upload_special_assignment_hint",
        "ui_drop": "upload_special_assignment_drop",
        "summary_icon": "bi-briefcase",
        "zone_icon": "bi-file-earmark-person",
        "details_id": "specialAssignmentDeckDetails",
    },
    {
        "kind": "accApprovedMoM",
        "source_key": "acc_approved_mom_decks",
        "field_prefix": "acc_approved_mom_deck",
        "file_stem_prefix": "acc_approved_mom_deck",
        "ui_label": "upload_acc_approved_mom_label",
        "ui_hint": "upload_acc_approved_mom_hint",
        "ui_drop": "upload_acc_approved_mom_drop",
        "summary_icon": "bi-journal-check",
        "zone_icon": "bi-file-earmark-check",
        "details_id": "accApprovedMoMDeckDetails",
    },
]


def _existing_excel_names(dashboard) -> list[str]:
    if not dashboard or not isinstance(dashboard.source_files, dict):
        return []
    names = dashboard.source_files.get("excel") or []
    if isinstance(names, str):
        token = names.strip()
        return [token] if token else []
    return [str(n).strip() for n in names if str(n).strip()]


def _excel_remove_requested(request) -> bool:
    return request.POST.get("remove_excel") == "1"


def _resubmit_can_keep_existing_excel(request, resubmit_dashboard, template_type: str) -> bool:
    if not resubmit_dashboard or _excel_remove_requested(request):
        return False
    if excel_uploads_from_request(request):
        return False
    if resubmit_dashboard.template_type != template_type:
        return False
    session = resubmit_dashboard.upload_session
    return bool(session and session.raw_data_json)


def _resubmit_update_metadata_and_attachments(
    request,
    resubmit_dashboard,
    *,
    dashboard_name: str,
    icon: str,
    template_type: str,
    description: str,
    active_company,
) -> "Dashboard":
    from reports_app.dashboard_workflow import mark_dashboard_draft

    existing_source = (
        resubmit_dashboard.source_files
        if isinstance(resubmit_dashboard.source_files, dict)
        else {}
    )
    resolved_decks = _resolve_all_deck_attachments(
        request,
        resubmit_dashboard.report_id,
        existing_source=existing_source,
        is_resubmit=True,
        company=active_company,
    )
    excel_names = _existing_excel_names(resubmit_dashboard)
    source_files_info = dict(existing_source)
    source_files_info.update(resolved_decks)
    if excel_names:
        source_files_info["excel"] = excel_names

    resubmit_dashboard.name = dashboard_name
    resubmit_dashboard.description = description
    resubmit_dashboard.icon = icon
    resubmit_dashboard.template_type = template_type
    resubmit_dashboard.html_file = ""
    resubmit_dashboard.source_files = source_files_info
    if not resubmit_dashboard.company_id:
        resubmit_dashboard.company = active_company
    mark_dashboard_draft(resubmit_dashboard)
    resubmit_dashboard.save(
        update_fields=[
            "name",
            "description",
            "icon",
            "template_type",
            "html_file",
            "source_files",
            "company",
            "status",
            "published_at",
        ]
    )
    return resubmit_dashboard


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


def inject_user_edits_persist_script(html_out: str, user_edits_json: str) -> str:
    """Insert or replace the audit-dashboard-user-persist JSON block."""
    raw = str(user_edits_json or "").strip()
    if not raw:
        return html_out
    safe = raw.replace("</", "<\\/")
    script = (
        f'<script id="audit-dashboard-user-persist" type="application/json">{safe}</script>'
    )
    cleaned = re.sub(
        r'<script id="audit-dashboard-user-persist"[^>]*>.*?</script>\s*',
        "",
        html_out,
        flags=re.DOTALL,
    )
    if re.search(r"<body\b", cleaned, flags=re.IGNORECASE):
        return re.sub(
            r"(<body[^>]*>)",
            r"\1\n" + script,
            cleaned,
            count=1,
            flags=re.IGNORECASE,
        )
    return script + cleaned


def inject_dashboard_serve_context(
    html_out: str,
    *,
    mail_url: str,
    plan_url: str,
    user_edits_save_url: str | None,
    can_save_user_edits: bool,
    user_edits_json: str = "",
) -> str:
    h = inject_web_mail_api(html_out, mail_url, plan_url)
    try:
        h = h.replace(
            _USER_EDITS_SAVE_MARKER,
            f"window.__AI_EXCEL_USER_EDITS_SAVE_URL__={json.dumps(user_edits_save_url or '')};",
        )
        h = h.replace(
            _CAN_SAVE_USER_EDITS_MARKER,
            f"window.__AI_EXCEL_CAN_SAVE_USER_EDITS__={'true' if can_save_user_edits else 'false'};",
        )
        if user_edits_json and str(user_edits_json).strip():
            h = inject_user_edits_persist_script(h, user_edits_json)
        return h
    except Exception:
        return h


def validate_dashboard_user_edits_payload(data: dict) -> dict:
    """Normalize client audit-plan persistence payload."""
    if not isinstance(data, dict):
        raise ValueError("invalid_payload")
    version = data.get("v")
    if version != 1:
        raise ValueError("invalid_version")

    plan_rows_out: list[list[str]] = []
    for row in data.get("planRows") or []:
        if not isinstance(row, list):
            continue
        cells = [str(c if c is not None else "").strip() for c in row[:7]]
        while len(cells) < 7:
            cells.append("")
        plan_rows_out.append(cells)

    plan_bg_out: list[list[str]] = []
    for row in data.get("planCellBg") or []:
        if not isinstance(row, list):
            continue
        colors: list[str] = []
        for c in row[:7]:
            s = str(c if c is not None else "#ffffff").strip()
            colors.append(s if re.fullmatch(r"#[0-9a-fA-F]{6}", s) else "#ffffff")
        while len(colors) < 7:
            colors.append("#ffffff")
        plan_bg_out.append(colors)

    reviews_note = data.get("reviewsNote")
    if reviews_note is not None and not isinstance(reviews_note, str):
        raise ValueError("invalid_reviews_note")

    return {
        "v": 1,
        "planRows": plan_rows_out,
        "planCellBg": plan_bg_out,
        "reviewsNote": str(reviews_note or ""),
    }


def update_dashboard_review_attachments(
    request,
    dashboard,
    *,
    company=None,
) -> None:
    """Replace deck attachments for a dashboard under review (Excel unchanged)."""
    from audit_app.models import DashboardStatus

    if dashboard.status != DashboardStatus.UNDER_REVIEW:
        raise ValueError("not_under_review")

    existing_source = (
        dashboard.source_files if isinstance(dashboard.source_files, dict) else {}
    )
    resolved = _resolve_all_deck_attachments(
        request,
        dashboard.report_id,
        existing_source=existing_source,
        is_resubmit=True,
        company=company or dashboard.company,
    )
    source_files_info = dict(existing_source)
    source_files_info.update(resolved)
    if "excel" not in source_files_info and existing_source.get("excel"):
        source_files_info["excel"] = list(existing_source.get("excel") or [])
    dashboard.source_files = source_files_info
    dashboard.html_file = ""
    dashboard.save(update_fields=["source_files", "html_file"])


def excel_uploads_from_request(request) -> list:
    files = []
    for key in ("file1", "file2", "file3", "file4"):
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


def _existing_media_paths(relative_paths: list[str] | None) -> list[str]:
    from django.conf import settings as _settings

    root = Path(_settings.MEDIA_ROOT)
    return [rel for rel in (relative_paths or []) if (root / rel).is_file()]


def _delete_media_relative_files(relative_paths: list[str]) -> None:
    from django.conf import settings as _settings

    root = Path(_settings.MEDIA_ROOT)
    for rel in relative_paths:
        p = root / rel
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                pass


def _resolve_deck_attachment_paths(
    request,
    report_id: str,
    *,
    field_prefix: str,
    file_stem_prefix: str,
    existing_paths: list[str] | None,
    is_resubmit: bool,
) -> list[str]:
    existing_valid = _existing_media_paths(existing_paths)
    new_upload = request.FILES.get(f"{field_prefix}1")
    has_new = bool(new_upload and str(getattr(new_upload, "name", "")).strip())
    remove = request.POST.get(f"remove_{field_prefix}") == "1"

    if has_new:
        new_paths = _save_uploaded_decks_to_media(
            request,
            report_id,
            field_prefix=field_prefix,
            file_stem_prefix=file_stem_prefix,
        )
        old_to_delete = [p for p in existing_valid if p not in new_paths]
        if old_to_delete:
            _delete_media_relative_files(old_to_delete)
        return new_paths

    if is_resubmit:
        if remove:
            if existing_valid:
                _delete_media_relative_files(existing_valid)
            return []
        return list(existing_valid)

    return []


def _resolve_all_deck_attachments(
    request,
    report_id: str,
    *,
    existing_source: dict | None,
    is_resubmit: bool,
    company=None,
) -> dict[str, list[str]]:
    from audit_app.company_access import get_enabled_attachment_kinds
    from dashboard_locale import normalize_locale, tr

    existing_source = existing_source if isinstance(existing_source, dict) else {}
    enabled_kinds = get_enabled_attachment_kinds(company)
    locale = normalize_locale(request.session.get("ui_lang", "en"))
    resolved: dict[str, list[str]] = {}
    for spec in ATTACHMENT_SPECS:
        kind = spec["kind"]
        field_prefix = spec["field_prefix"]
        has_upload = bool(
            request.FILES.get(f"{field_prefix}1")
            and str(getattr(request.FILES.get(f"{field_prefix}1"), "name", "")).strip()
        )
        wants_remove = request.POST.get(f"remove_{field_prefix}") == "1"

        if kind not in enabled_kinds:
            if has_upload or (wants_remove and not is_resubmit):
                raise ValueError(tr(locale, "err_attachment_disabled", label=spec["kind"]))
            if is_resubmit:
                resolved[spec["source_key"]] = list(
                    _existing_media_paths(existing_source.get(spec["source_key"]))
                )
            else:
                resolved[spec["source_key"]] = []
            continue

        resolved[spec["source_key"]] = _resolve_deck_attachment_paths(
            request,
            report_id,
            field_prefix=field_prefix,
            file_stem_prefix=spec["file_stem_prefix"],
            existing_paths=existing_source.get(spec["source_key"]),
            is_resubmit=is_resubmit,
        )
    return resolved


def build_attachment_form_slots(
    dashboard,
    locale: str = "en",
    company=None,
) -> list[dict[str, Any]]:
    from audit_app.company_access import get_enabled_attachment_kinds
    from web_strings import get_ui

    ui = get_ui(locale)
    enabled_kinds = get_enabled_attachment_kinds(company)
    source = dashboard.source_files if dashboard and isinstance(dashboard.source_files, dict) else {}
    slots: list[dict[str, Any]] = []
    for spec in ATTACHMENT_SPECS:
        if spec["kind"] not in enabled_kinds:
            continue
        paths = _existing_media_paths(source.get(spec["source_key"]))
        hint_key = spec.get("ui_hint") or ""
        slots.append(
            {
                **spec,
                "label": ui.get(spec["ui_label"], ""),
                "hint": ui.get(hint_key, "") if hint_key else "",
                "drop": ui.get(spec["ui_drop"], ""),
                "has_existing": bool(paths),
                "existing_name": Path(paths[0]).name if paths else "",
            }
        )
    return slots


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


def _attachment_path_kwargs(
    source_files: dict,
    enabled_kinds: set[str],
    *,
    multi_index: int | None = None,
    multi_total: int | None = None,
) -> dict[str, str | None]:
    """Build generate_finance_report attachment path kwargs, scoped by company settings."""
    rel_by_kind = {
        "deck": source_files.get("decks") or [],
        "highRisk": source_files.get("high_risk_decks") or [],
        "tgaViolations": source_files.get("tga_violations_decks") or [],
        "missingVehicle": source_files.get("missing_vehicle_decks") or [],
        "internalAuditQuarterly": source_files.get("internal_audit_quarterly_decks") or [],
        "specialAssignment": source_files.get("special_assignment_decks") or [],
        "accApprovedMoM": source_files.get("acc_approved_mom_decks") or [],
    }
    param_by_kind = {
        "deck": "attached_deck_path",
        "highRisk": "attached_high_risk_deck_path",
        "tgaViolations": "attached_tga_violations_deck_path",
        "missingVehicle": "attached_missing_vehicle_deck_path",
        "internalAuditQuarterly": "attached_internal_audit_quarterly_deck_path",
        "specialAssignment": "attached_special_assignment_deck_path",
        "accApprovedMoM": "attached_acc_approved_mom_deck_path",
    }
    kwargs: dict[str, str | None] = {}
    for kind, param in param_by_kind.items():
        rel = rel_by_kind[kind]
        if kind not in enabled_kinds:
            kwargs[param] = None
        elif multi_index is None:
            kwargs[param] = _first_attached_deck_path(rel)
        else:
            abs_paths = _abs_media_paths(rel)
            kwargs[param] = _attached_deck_for_index(abs_paths, multi_index, multi_total or 1)
    return kwargs


def report_locale_for_dashboard(dashboard, request) -> str:
    """Locale for generated report HTML (iframe content). AI dashboards are English-only."""
    template = getattr(dashboard, "template_type", None)
    if template == TEMPLATE_CODE_IAD:
        return "en"
    if template == TEMPLATE_CODE_CD:
        return "ar"
    return normalize_locale(request.session.get("ui_lang", "en"))


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


def version_payload(module_file: str) -> dict[str, str]:
    return {"report_version": REPORT_VERSION, "module_file": module_file}


# ── New architecture: store-only upload + on-demand generation ────────


def _ar_compliance_err(locale: str, ar: str, en: str) -> str:
    return ar if locale == "ar" else en


def _assert_ar_compliance_upload_request(request, uploads, locale: str) -> None:
    from arabic_compliance_dashboard.schema import EXCEL_EXTENSIONS

    if len(uploads) != 1:
        raise ValueError(
            _ar_compliance_err(
                locale,
                "قالب الالتزام العربي يقبل ملف Excel واحد فقط.",
                "Arabic compliance template accepts one Excel file only.",
            )
        )
    ext = Path(uploads[0].name).suffix.lower()
    if ext not in EXCEL_EXTENSIONS:
        raise ValueError(
            _ar_compliance_err(
                locale,
                "صيغة الملف غير مدعومة. استخدم .xlsx أو .xls أو .xlsm",
                "Unsupported file type. Use .xlsx, .xls, or .xlsm.",
            )
        )
    extra_keys = ("file2", "file3", "file4")
    for key in extra_keys:
        f = request.FILES.get(key)
        if f and str(getattr(f, "name", "")).strip():
            raise ValueError(
                _ar_compliance_err(
                    locale,
                    "قالب الالتزام العربي لا يقبل ملفات Excel إضافية.",
                    "Arabic compliance template does not accept extra Excel files.",
                )
            )
    for key in request.FILES:
        if key.startswith("deck") or key.startswith("remove_deck"):
            raise ValueError(
                _ar_compliance_err(
                    locale,
                    "قالب الالتزام العربي لا يقبل مرفقات PPTX/PDF.",
                    "Arabic compliance template does not accept deck attachments.",
                )
            )


def _store_ar_compliance_upload(
    request,
    dashboard_name: str,
    icon: str,
    description: str,
    *,
    resubmit_dashboard: "Dashboard | None",
    ui_locale: str,
    active_company,
) -> "Dashboard":
    import uuid

    import pandas as pd
    from audit_app.models import Dashboard, DashboardStatus, ICON_CHOICES, UploadSession
    from audit_app.services.persistence import persist_report_result
    from arabic_compliance_dashboard.data import (
        minimal_audit_payload,
        prepare_upload_dataframe,
        validate_ar_companies_for_tenant,
    )
    from arabic_compliance_dashboard.schema import TEMPLATE_CODE
    from reports_app.dashboard_workflow import mark_dashboard_draft

    sheet = None
    uploads = excel_uploads_from_request(request)
    remove_excel = _excel_remove_requested(request)

    if resubmit_dashboard and not uploads:
        if remove_excel:
            raise ValueError(tr(ui_locale, "upload_excel_removed_need_file"))
        if _resubmit_can_keep_existing_excel(request, resubmit_dashboard, TEMPLATE_CODE):
            valid_icons = {v for v, _ in ICON_CHOICES}
            if icon not in valid_icons:
                icon = "bi-bar-chart-line-fill"
            return _resubmit_update_metadata_and_attachments(
                request,
                resubmit_dashboard,
                dashboard_name=dashboard_name,
                icon=icon,
                template_type=TEMPLATE_CODE,
                description=description,
                active_company=active_company,
            )
        raise ValueError(tr(ui_locale, "web_err_no_file"))

    _assert_ar_compliance_upload_request(request, uploads, ui_locale)

    with tempfile.TemporaryDirectory() as tmp_dir:
        up = uploads[0]
        path = _persist_upload(up, tmp_dir)
        df = read_input_file(path, sheet_name=sheet, locale=ui_locale)
        if isinstance(df, dict):
            first_key = next(iter(df.keys()))
            df = df[first_key]
        df = df.dropna(how="all").dropna(axis=1, how="all")
        if df.empty:
            raise ValueError(tr(ui_locale, "web_err_empty"))

        df = prepare_upload_dataframe(df, locale=ui_locale)
        validate_ar_companies_for_tenant(df, active_company, locale=ui_locale)

        primary_name = up.name
        primary_sha256 = content_fingerprint(df, up.name)

        report_id = (
            resubmit_dashboard.report_id
            if resubmit_dashboard
            else str(uuid.uuid4())
        )
        primary_audit_payload = minimal_audit_payload(report_id=report_id, df=df)

        if resubmit_dashboard:
            old_session = resubmit_dashboard.upload_session
            if old_session:
                resubmit_dashboard.upload_session = None
                resubmit_dashboard.save(update_fields=["upload_session"])
                old_session.delete()

        session = persist_report_result(
            source_name=primary_name,
            sheet_name=sheet,
            locale="ar",
            mode=TEMPLATE_CODE,
            content_sha256=primary_sha256,
            observation_rows=[],
            audit_payload=primary_audit_payload,
        )

        entry = json.loads(
            df.to_json(orient="split", force_ascii=False, default_handler=str)
        )
        entry["source_name"] = primary_name
        if isinstance(session, UploadSession):
            session.raw_data_json = json.dumps(entry, ensure_ascii=False)
            session.save(update_fields=["raw_data_json"])

        source_files_info = {"excel": [primary_name]}

        if resubmit_dashboard:
            resubmit_dashboard.name = dashboard_name
            resubmit_dashboard.description = description
            resubmit_dashboard.icon = icon
            resubmit_dashboard.template_type = TEMPLATE_CODE
            resubmit_dashboard.html_file = ""
            resubmit_dashboard.source_files = source_files_info
            resubmit_dashboard.upload_session = session
            if not resubmit_dashboard.company_id:
                resubmit_dashboard.company = active_company
            mark_dashboard_draft(resubmit_dashboard)
            resubmit_dashboard.save(
                update_fields=[
                    "name",
                    "description",
                    "icon",
                    "template_type",
                    "html_file",
                    "source_files",
                    "upload_session",
                    "company",
                    "status",
                    "published_at",
                ]
            )
            return resubmit_dashboard

        return Dashboard.objects.create(
            name=dashboard_name,
            description=description,
            icon=icon,
            template_type=TEMPLATE_CODE,
            report_id=report_id,
            html_file="",
            source_files=source_files_info,
            company=active_company,
            created_by=request.user if request.user.is_authenticated else None,
            upload_session=session,
            status=DashboardStatus.DRAFT,
        )


def store_upload_to_db(
    request,
    dashboard_name: str,
    icon: str,
    template_type: str = DEFAULT_DASHBOARD_TEMPLATE_CODE,
    description: str = "",
    *,
    resubmit_dashboard: "Dashboard | None" = None,
) -> "Dashboard":
    """
    Read uploaded Excel files (file1 required; file2-4 optional), store ALL
    row data in the DB as JSON, persist audit observation records, and create
    a Dashboard record.

    Deck/plan files (deck1, high_risk_deck1, tga_violations_deck1, missing_vehicle_deck1,
    internal_audit_quarterly_deck1, special_assignment_deck1, acc_approved_mom_deck1)
    are saved to media/decks/<report_id>/
    and embedded in the dashboard HTML when it is generated on view.

    Returns the created Dashboard instance.
    Raises ValueError with a user-facing message on bad input.
    """
    import pandas as pd
    from django.conf import settings as _settings
    from audit_app.models import Dashboard, DashboardStatus, ICON_CHOICES, UploadSession
    from audit_app.company_access import (
        extract_excel_company_names_from_df,
        extract_excel_subcompany_names_from_df,
        resolve_tenant_company,
        validate_excel_company_for_tenant,
        validate_excel_subcompanies_for_tenant,
    )
    from reports_app.dashboard_workflow import mark_dashboard_draft

    ui_locale = normalize_locale(request.session.get("ui_lang", "en"))
    active_company = resolve_tenant_company(getattr(request, "active_company", None))
    if active_company is None:
        raise ValueError(tr(ui_locale, "err_no_active_company"))
    sheet = None
    uploads = excel_uploads_from_request(request)
    remove_excel = _excel_remove_requested(request)

    if resubmit_dashboard and not uploads:
        if remove_excel:
            raise ValueError(tr(ui_locale, "upload_excel_removed_need_file"))
        if _resubmit_can_keep_existing_excel(request, resubmit_dashboard, template_type):
            valid_icons = {v for v, _ in ICON_CHOICES}
            if icon not in valid_icons:
                icon = "bi-bar-chart-line-fill"
            return _resubmit_update_metadata_and_attachments(
                request,
                resubmit_dashboard,
                dashboard_name=dashboard_name,
                icon=icon,
                template_type=template_type,
                description=description,
                active_company=active_company,
            )
        raise ValueError(tr(ui_locale, "web_err_no_file"))

    if not uploads:
        raise ValueError(tr(ui_locale, "web_err_no_file"))

    # Validate icon choice
    valid_icons = {v for v, _ in ICON_CHOICES}
    if icon not in valid_icons:
        icon = "bi-bar-chart-line-fill"

    if template_type == TEMPLATE_CODE_CD:
        return _store_ar_compliance_upload(
            request,
            dashboard_name,
            icon,
            description,
            resubmit_dashboard=resubmit_dashboard,
            ui_locale=ui_locale,
            active_company=active_company,
        )

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

        excel_companies = extract_excel_company_names_from_df(primary_df, ui_locale)
        validate_excel_company_for_tenant(active_company, excel_companies, locale=ui_locale)
        excel_subcompanies = extract_excel_subcompany_names_from_df(primary_df, ui_locale)
        validate_excel_subcompanies_for_tenant(
            active_company, excel_subcompanies, locale=ui_locale
        )

        # ── Persist audit observation records (primary file only) ─────
        _, audit_payload = generate_finance_report(
            primary_df,
            source_name=primary_name,
            sheet_name=sheet,
            locale=ui_locale,
            allow_multiple_audit_companies=False,
            company_entity=active_company,
        )
        primary_audit_payload = audit_payload or {}
        if resubmit_dashboard:
            primary_audit_payload["report_id"] = resubmit_dashboard.report_id
            # Remove old upload data before reusing the same report_id (unique on ReportArtifact).
            old_session = resubmit_dashboard.upload_session
            if old_session:
                resubmit_dashboard.upload_session = None
                resubmit_dashboard.save(update_fields=["upload_session"])
                old_session.delete()

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

        report_id = (
            resubmit_dashboard.report_id
            if resubmit_dashboard
            else (primary_audit_payload.get("report_id") or str(uuid.uuid4()))
        )

        # ── Save deck/plan files to media ────────────────────────────
        existing_source = (
            resubmit_dashboard.source_files
            if resubmit_dashboard and isinstance(resubmit_dashboard.source_files, dict)
            else {}
        )
        is_resubmit = resubmit_dashboard is not None
        resolved_decks = _resolve_all_deck_attachments(
            request,
            report_id,
            existing_source=existing_source,
            is_resubmit=is_resubmit,
            company=active_company,
        )

        source_files_info = {
            "excel": all_names,
            **resolved_decks,
        }

        if resubmit_dashboard:
            resubmit_dashboard.name = dashboard_name
            resubmit_dashboard.description = description
            resubmit_dashboard.icon = icon
            resubmit_dashboard.template_type = template_type
            resubmit_dashboard.html_file = ""
            resubmit_dashboard.source_files = source_files_info
            resubmit_dashboard.upload_session = (
                session if isinstance(session, UploadSession) else None
            )
            if not resubmit_dashboard.company_id:
                resubmit_dashboard.company = active_company
            mark_dashboard_draft(resubmit_dashboard)
            resubmit_dashboard.save(
                update_fields=[
                    "name",
                    "description",
                    "icon",
                    "template_type",
                    "html_file",
                    "source_files",
                    "upload_session",
                    "company",
                    "status",
                    "published_at",
                ]
            )
            return resubmit_dashboard

        dashboard = Dashboard.objects.create(
            name=dashboard_name,
            description=description,
            icon=icon,
            template_type=template_type,
            report_id=report_id,
            html_file="",
            source_files=source_files_info,
            company=active_company,
            created_by=request.user if request.user.is_authenticated else None,
            upload_session=session if isinstance(session, UploadSession) else None,
            status=DashboardStatus.DRAFT,
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

    from audit_app.company_access import get_enabled_attachment_kinds

    session = dashboard.upload_session
    if not session or not session.raw_data_json:
        raise ValueError("No stored data for this dashboard.")

    if getattr(dashboard, "template_type", None) == TEMPLATE_CODE_CD:
        from arabic_compliance_dashboard.data import dataframe_from_dashboard, main_brand_logo_pack
        from arabic_compliance_dashboard.generator import generate_ar_compliance_report

        df = dataframe_from_dashboard(dashboard)
        api_base = f"/dashboards/{dashboard.pk}/ar-api"
        brand_logos, default_brand_code = main_brand_logo_pack(dashboard.company)
        return generate_ar_compliance_report(
            df,
            dashboard_id=dashboard.pk,
            api_base=api_base,
            brand_logos=brand_logos,
            default_brand_code=default_brand_code,
        )

    # AI dashboards are always English; others follow the UI language.
    if getattr(dashboard, "template_type", None) == TEMPLATE_CODE_IAD:
        locale = "en"
    elif locale is None:
        locale = request.session.get("ui_lang", session.locale or "en")
    locale = normalize_locale(locale)

    raw = json.loads(session.raw_data_json)

    mail_url = request.build_absolute_uri("/api/send-obs-email")
    plan_url = request.build_absolute_uri("/api/parse-audit-plan-pptx")

    source_files = dashboard.source_files or {}
    if not isinstance(source_files, dict):
        source_files = {}
    enabled_kinds = get_enabled_attachment_kinds(dashboard.company)
    attachment_kwargs = _attachment_path_kwargs(source_files, enabled_kinds)

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
            allow_multiple_audit_companies=False,
            enabled_attachment_kinds=enabled_kinds,
            company_entity=dashboard.company,
            **attachment_kwargs,
        )
    else:
        # Multi-file: build tabs
        tabs = []
        n_entries = len(entries)
        for i, e in enumerate(entries):
            df = pd.DataFrame(e["data"], columns=e["columns"])
            source = e.get("source_name", "file")
            tab_attachment_kwargs = _attachment_path_kwargs(
                source_files,
                enabled_kinds,
                multi_index=i,
                multi_total=n_entries,
            )
            tab_html, _ = generate_finance_report(
                df,
                source_name=source,
                sheet_name=session.sheet_name or None,
                locale=locale,
                allow_multiple_audit_companies=False,
                enabled_attachment_kinds=enabled_kinds,
                company_entity=dashboard.company,
                **tab_attachment_kwargs,
            )
            title = workbook_dashboard_tab_title(df, source, locale)
            tabs.append((tab_html, title))

        html_out = build_multi_dashboard_shell(
            [(h, t, None, None) for h, t in tabs],
            locale=locale,
            mail_api_url=mail_url,
            plan_parse_api_url=plan_url,
        )

    result = inject_web_mail_api(html_out, mail_url, plan_url)

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
