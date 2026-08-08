"""Django report orchestration: store uploads, lazy HTML generation, attachment handling."""
from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from html import escape as html_escape
from pathlib import Path
from typing import Any

from django.utils.text import get_valid_filename

from ai_excel_dashboard import (
    _CAN_SAVE_USER_EDITS_MARKER,
    _CAN_SAVE_USER_EDITS_META_MARKER,
    _MAIL_API_MARKER,
    _PLAN_PARSE_API_MARKER,
    _USER_EDITS_SAVE_MARKER,
    _USER_EDITS_SAVE_META_MARKER,
    AUDIT_BUNDLE_MAX_FILES,
    REPORT_VERSION,
    build_multi_dashboard_shell,
    content_fingerprint,
    generate_finance_report,
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
    {
        "kind": "internalAuditDetailed",
        "source_key": "internal_audit_detailed_decks",
        "field_prefix": "internal_audit_detailed_deck",
        "file_stem_prefix": "internal_audit_detailed_deck",
        "ui_label": "upload_internal_audit_detailed_label",
        "ui_hint": "upload_internal_audit_detailed_hint",
        "ui_drop": "upload_internal_audit_detailed_drop",
        "summary_icon": "bi-file-earmark-richtext",
        "zone_icon": "bi-file-earmark-text",
        "details_id": "internalAuditDetailedDeckDetails",
    },
]

ATTACHMENT_MAX_FILES = 20  # hard ceiling; per-kind limits come from company settings
DEFAULT_ATTACHMENT_MAX_FILES = 4
_SAFE_UPLOAD_STEM_MAX = 120

# Kind code → chart_payload key for embedded slide decks.
ATTACHMENT_KIND_PAYLOAD_KEYS: dict[str, str] = {
    "deck": "embedded_slide_deck",
    "highRisk": "embedded_high_risk_slide_deck",
    "tgaViolations": "embedded_tga_violations_slide_deck",
    "missingVehicle": "embedded_missing_vehicle_slide_deck",
    "internalAuditQuarterly": "embedded_internal_audit_quarterly_slide_deck",
    "specialAssignment": "embedded_special_assignment_slide_deck",
    "accApprovedMoM": "embedded_acc_approved_mom_slide_deck",
    "internalAuditDetailed": "embedded_internal_audit_detailed_slide_deck",
}

# Kind code → checkbox id used by build_deck_attach_toggle_html.
ATTACHMENT_KIND_TOGGLE_IDS: dict[str, str] = {
    "deck": "audit-deck-attach-cb",
    "highRisk": "audit-high-risk-cb",
    "tgaViolations": "audit-tga-violations-cb",
    "missingVehicle": "audit-missing-vehicle-cb",
    "internalAuditQuarterly": "audit-internal-audit-quarterly-cb",
    "specialAssignment": "audit-special-assignment-cb",
    "accApprovedMoM": "audit-acc-approved-mom-cb",
    "internalAuditDetailed": "audit-internal-audit-detailed-cb",
}

_PAYLOAD_CONST_RE = re.compile(r"const\s+payload\s*=\s*")


def filter_dashboard_html_attachments(
    html_content: str,
    allowed_kinds: set[str] | frozenset[str],
) -> str:
    """
    Strip embedded attachment payloads and toggles not in ``allowed_kinds``.

    Used when serving cached HTML to assigned viewers with per-kind grants so
    denied base64 decks never reach the browser.
    """
    allowed = frozenset(allowed_kinds)
    denied_kinds = [
        kind for kind in ATTACHMENT_KIND_PAYLOAD_KEYS if kind not in allowed
    ]
    if not denied_kinds:
        return html_content

    h = html_content
    match = _PAYLOAD_CONST_RE.search(h)
    if match:
        start = match.end()
        try:
            payload, end_idx = json.JSONDecoder().raw_decode(h, start)
        except (json.JSONDecodeError, ValueError, TypeError):
            payload = None
            end_idx = start
        if isinstance(payload, dict):
            for kind in denied_kinds:
                key = ATTACHMENT_KIND_PAYLOAD_KEYS.get(kind)
                if key and key in payload:
                    payload[key] = None
            new_json = json.dumps(payload, ensure_ascii=False)
            h = h[:start] + new_json + h[end_idx:]

    for kind in denied_kinds:
        cb_id = ATTACHMENT_KIND_TOGGLE_IDS.get(kind)
        if not cb_id:
            continue
        # Remove the whole toggle label wrapping the denied checkbox.
        pattern = re.compile(
            r'<label\s+class="audit-obs-aging-toggle">\s*'
            rf'<input\s+type="checkbox"\s+id="{re.escape(cb_id)}"[^>]*>'
            r".*?</label>",
            re.DOTALL | re.IGNORECASE,
        )
        h = pattern.sub("", h)

    return h


def _safe_upload_stem(filename: str, *, fallback: str = "file") -> str:
    """Preserve Arabic/Latin letters and case; strip only unsafe filesystem characters.

    Django's ASCII-only slugify would turn Arabic-only names into an empty stem
    (then a generic fallback), which made uploads look lost and removed identity.
    """
    from django.core.exceptions import SuspiciousFileOperation

    base = Path(str(filename or "").replace("\\", "/")).name
    raw = Path(base).stem.replace("\x00", "").strip()
    try:
        cleaned = get_valid_filename(raw) if raw else ""
    except SuspiciousFileOperation:
        cleaned = ""
    cleaned = re.sub(r'[<>:"/\\|?*]', "", cleaned)
    cleaned = cleaned.strip(" ._")
    if len(cleaned) > _SAFE_UPLOAD_STEM_MAX:
        cleaned = cleaned[:_SAFE_UPLOAD_STEM_MAX].rstrip(" ._")
    return cleaned or fallback


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


def _inject_before_head_close(html_out: str, snippet: str) -> str:
    """Append HTML snippet before </head> (or prefix if no head tag)."""
    if re.search(r"</head>", html_out, flags=re.IGNORECASE):
        return re.sub(
            r"</head>",
            snippet + "\n</head>",
            html_out,
            count=1,
            flags=re.IGNORECASE,
        )
    return snippet + html_out


def inject_dashboard_serve_context(
    html_out: str,
    *,
    mail_url: str,
    plan_url: str,
    user_edits_save_url: str | None,
    can_save_user_edits: bool,
    user_edits_json: str = "",
    allowed_attachment_kinds: set[str] | frozenset[str] | None = None,
) -> str:
    h = inject_web_mail_api(html_out, mail_url, plan_url)
    if allowed_attachment_kinds is not None:
        h = filter_dashboard_html_attachments(h, allowed_attachment_kinds)
    save_js = f"window.__AI_EXCEL_USER_EDITS_SAVE_URL__={json.dumps(user_edits_save_url or '')};"
    can_js = (
        f"window.__AI_EXCEL_CAN_SAVE_USER_EDITS__="
        f"{'true' if can_save_user_edits else 'false'};"
    )
    save_meta = html_escape(user_edits_save_url or "", quote=True)
    can_meta = "true" if can_save_user_edits else "false"
    try:
        if _USER_EDITS_SAVE_MARKER in h:
            h = h.replace(_USER_EDITS_SAVE_MARKER, save_js)
        elif "window.__AI_EXCEL_USER_EDITS_SAVE_URL__" not in h:
            h = _inject_before_head_close(h, f"<script>{save_js}\n{can_js}</script>")
        if _CAN_SAVE_USER_EDITS_MARKER in h:
            h = h.replace(_CAN_SAVE_USER_EDITS_MARKER, can_js)
        if _USER_EDITS_SAVE_META_MARKER in h:
            h = h.replace(_USER_EDITS_SAVE_META_MARKER, save_meta)
        if _CAN_SAVE_USER_EDITS_META_MARKER in h:
            h = h.replace(_CAN_SAVE_USER_EDITS_META_MARKER, can_meta)
        if user_edits_json and str(user_edits_json).strip():
            h = inject_user_edits_persist_script(h, user_edits_json)
        return h
    except Exception:
        return h


def _format_plan_pct_cell(value) -> str:
    """Normalize audit-plan percentage cells to a display value like 50%."""
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        n = float(value)
        if n > 0 and n <= 1:
            n *= 100
        rounded = round(n, 2)
        disp = str(int(rounded)) if rounded == int(rounded) else str(rounded)
        return f"{disp}%"
    s = str(value).strip()
    if not s:
        return ""
    if "%" in s:
        m = re.match(r"^([\d.,]+)\s*%?\s*$", s)
        if m:
            num = float(m.group(1).replace(",", "."))
            if num > 0 and num <= 1:
                num *= 100
            rounded = round(num, 2)
            disp = str(int(rounded)) if rounded == int(rounded) else str(rounded)
            return f"{disp}%"
        return re.sub(r"\s+", "", s)
    m2 = re.match(r"^([\d.,]+)$", s)
    if m2:
        num = float(m2.group(1).replace(",", "."))
        if num > 0 and num <= 1:
            num *= 100
        rounded = round(num, 2)
        disp = str(int(rounded)) if rounded == int(rounded) else str(rounded)
        return f"{disp}%"
    return s


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
        for idx in (4, 5, 6):
            cells[idx] = _format_plan_pct_cell(cells[idx])
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

    obs_tracking_out: list[list[str]] = []
    for row in data.get("obsTrackingRows") or []:
        if not isinstance(row, list):
            continue
        cells = [str(c if c is not None else "").strip() for c in row[:5]]
        while len(cells) < 5:
            cells.append("")
        obs_tracking_out.append(cells)

    return {
        "v": 1,
        "planRows": plan_rows_out,
        "planCellBg": plan_bg_out,
        "reviewsNote": str(reviews_note or ""),
        "obsTrackingRows": obs_tracking_out,
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


def _deck_uploads_from_request(
    request, field_prefix: str, *, max_files: int | None = None
) -> list:
    """Collect uploaded deck files: multi-select field and legacy numbered fields."""
    limit = max(1, int(max_files or ATTACHMENT_MAX_FILES))
    uploads: list = []
    seen: set[int] = set()
    for f in request.FILES.getlist(field_prefix):
        if f and str(getattr(f, "name", "")).strip() and id(f) not in seen:
            seen.add(id(f))
            uploads.append(f)
    for i in range(1, ATTACHMENT_MAX_FILES + 1):
        f = request.FILES.get(f"{field_prefix}{i}")
        if f and str(getattr(f, "name", "")).strip() and id(f) not in seen:
            seen.add(id(f))
            uploads.append(f)
    return uploads[:limit]


def _save_uploaded_decks_to_media(
    request,
    report_id: str,
    *,
    field_prefix: str,
    file_stem_prefix: str,
    media_subdir: str = "decks",
    uploads: list | None = None,
    start_index: int = 1,
    max_files: int | None = None,
) -> list[str]:
    from django.conf import settings as _settings

    uploads = list(uploads) if uploads is not None else _deck_uploads_from_request(
        request, field_prefix, max_files=max_files
    )
    if not uploads:
        return []

    media_dir = Path(_settings.MEDIA_ROOT) / media_subdir / report_id
    media_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    used_names: set[str] = set()
    for offset, deck_up in enumerate(uploads):
        idx = start_index + offset
        safe_ext = Path(deck_up.name).suffix.lower()
        if safe_ext not in {".pptx", ".ppt", ".pdf"}:
            safe_ext = ".pptx"
        orig_stem = _safe_upload_stem(deck_up.name, fallback="file")
        fname = f"{file_stem_prefix}{idx}_{orig_stem}{safe_ext}"
        if fname in used_names or (media_dir / fname).exists():
            fname = f"{file_stem_prefix}{idx}_{orig_stem}_{uuid.uuid4().hex[:6]}{safe_ext}"
        used_names.add(fname)
        dest = media_dir / fname
        with dest.open("wb") as fh:
            for chunk in deck_up.chunks():
                fh.write(chunk)
        saved.append(f"{media_subdir}/{report_id}/{fname}")
    return saved


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


def _removed_item_tokens(request, field_prefix: str) -> set[str]:
    tokens: set[str] = set()
    for raw in request.POST.getlist(f"remove_{field_prefix}_item"):
        s = str(raw).strip().replace("\\", "/")
        if not s:
            continue
        tokens.add(s)
        tokens.add(Path(s).name)
    return tokens


def _resolve_deck_attachment_paths(
    request,
    report_id: str,
    *,
    field_prefix: str,
    file_stem_prefix: str,
    existing_paths: list[str] | None,
    is_resubmit: bool,
    max_files: int = DEFAULT_ATTACHMENT_MAX_FILES,
    locale: str = "en",
    kind_label: str = "",
) -> list[str]:
    from dashboard_locale import tr

    max_files = max(
        1, min(int(max_files or DEFAULT_ATTACHMENT_MAX_FILES), ATTACHMENT_MAX_FILES)
    )
    existing_valid = _existing_media_paths(existing_paths)
    remove_all = request.POST.get(f"remove_{field_prefix}") == "1"
    remove_tokens = _removed_item_tokens(request, field_prefix)
    new_uploads = _deck_uploads_from_request(
        request, field_prefix, max_files=ATTACHMENT_MAX_FILES
    )

    if remove_all:
        kept: list[str] = []
        to_delete = list(existing_valid)
        remove_tokens = set()
    else:
        kept = []
        to_delete = []
        for rel in existing_valid:
            name = Path(rel).name
            if rel in remove_tokens or name in remove_tokens:
                to_delete.append(rel)
            else:
                kept.append(rel)

    # Validate final count BEFORE mutating media files.
    planned_new = len(new_uploads)
    planned_total = len(kept) + planned_new
    if planned_total > max_files:
        raise ValueError(
            tr(
                locale,
                "err_attachment_max_files",
                max=max_files,
                label=kind_label or field_prefix,
                keep=len(kept),
                room=max(0, max_files - len(kept)),
                total=planned_total,
            )
        )

    if to_delete:
        _delete_media_relative_files(to_delete)

    if new_uploads:
        new_paths = _save_uploaded_decks_to_media(
            request,
            report_id,
            field_prefix=field_prefix,
            file_stem_prefix=file_stem_prefix,
            uploads=new_uploads,
            start_index=len(kept) + 1,
            max_files=len(new_uploads),
        )
        return (kept + new_paths)[:max_files]

    if is_resubmit or remove_all or to_delete:
        return kept[:max_files]

    return []


def _resolve_all_deck_attachments(
    request,
    report_id: str,
    *,
    existing_source: dict | None,
    is_resubmit: bool,
    company=None,
) -> dict[str, list[str]]:
    from audit_app.company_access import (
        get_attachment_max_files_map,
        get_enabled_attachment_kinds,
    )
    from dashboard_locale import normalize_locale, tr

    existing_source = existing_source if isinstance(existing_source, dict) else {}
    enabled_kinds = get_enabled_attachment_kinds(company)
    max_by_kind = get_attachment_max_files_map(company)
    locale = normalize_locale(request.session.get("ui_lang", "en"))
    resolved: dict[str, list[str]] = {}
    for spec in ATTACHMENT_SPECS:
        kind = spec["kind"]
        field_prefix = spec["field_prefix"]
        has_upload = bool(_deck_uploads_from_request(request, field_prefix))
        wants_remove = request.POST.get(f"remove_{field_prefix}") == "1"
        wants_item_remove = bool(request.POST.getlist(f"remove_{field_prefix}_item"))

        if kind not in enabled_kinds:
            if has_upload or ((wants_remove or wants_item_remove) and not is_resubmit):
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
            max_files=max_by_kind.get(kind, DEFAULT_ATTACHMENT_MAX_FILES),
            locale=locale,
            kind_label=kind,
        )
    return resolved


def build_attachment_form_slots(
    dashboard,
    locale: str = "en",
    company=None,
) -> list[dict[str, Any]]:
    from audit_app.company_access import (
        get_attachment_max_files_map,
        get_enabled_attachment_kinds,
    )
    from web_strings import get_ui

    ui = get_ui(locale)
    enabled_kinds = get_enabled_attachment_kinds(company)
    max_by_kind = get_attachment_max_files_map(company)
    source = dashboard.source_files if dashboard and isinstance(dashboard.source_files, dict) else {}
    slots: list[dict[str, Any]] = []
    for spec in ATTACHMENT_SPECS:
        if spec["kind"] not in enabled_kinds:
            continue
        paths = _existing_media_paths(source.get(spec["source_key"]))
        names = [Path(p).name for p in paths]
        items = [{"path": p, "name": Path(p).name} for p in paths]
        max_files = max_by_kind.get(spec["kind"], DEFAULT_ATTACHMENT_MAX_FILES)
        hint_key = spec.get("ui_hint") or ""
        slots.append(
            {
                **spec,
                "label": ui.get(spec["ui_label"], ""),
                "hint": ui.get(hint_key, "") if hint_key else "",
                "drop": ui.get(spec["ui_drop"], ""),
                "has_existing": bool(paths),
                "existing_name": names[0] if names else "",
                "existing_names": names,
                "existing_items": items,
                "existing_count": len(names),
                "max_files": max_files,
                "remaining_slots": max(0, max_files - len(paths)),
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


def _attachment_path_kwargs(
    source_files: dict,
    enabled_kinds: set[str],
    *,
    multi_index: int | None = None,
    multi_total: int | None = None,
) -> dict[str, list[str] | None]:
    """Build generate_finance_report attachment path-list kwargs, scoped by company settings."""
    del multi_index, multi_total  # All files under a kind are available in every tab.
    rel_by_kind = {
        "deck": source_files.get("decks") or [],
        "highRisk": source_files.get("high_risk_decks") or [],
        "tgaViolations": source_files.get("tga_violations_decks") or [],
        "missingVehicle": source_files.get("missing_vehicle_decks") or [],
        "internalAuditQuarterly": source_files.get("internal_audit_quarterly_decks") or [],
        "specialAssignment": source_files.get("special_assignment_decks") or [],
        "accApprovedMoM": source_files.get("acc_approved_mom_decks") or [],
        "internalAuditDetailed": source_files.get("internal_audit_detailed_decks") or [],
    }
    param_by_kind = {
        "deck": "attached_deck_paths",
        "highRisk": "attached_high_risk_deck_paths",
        "tgaViolations": "attached_tga_violations_deck_paths",
        "missingVehicle": "attached_missing_vehicle_deck_paths",
        "internalAuditQuarterly": "attached_internal_audit_quarterly_deck_paths",
        "specialAssignment": "attached_special_assignment_deck_paths",
        "accApprovedMoM": "attached_acc_approved_mom_deck_paths",
        "internalAuditDetailed": "attached_internal_audit_detailed_deck_paths",
    }
    kwargs: dict[str, list[str] | None] = {}
    for kind, param in param_by_kind.items():
        rel = rel_by_kind[kind]
        if kind not in enabled_kinds:
            kwargs[param] = None
        else:
            abs_paths = _abs_media_paths(rel)
            kwargs[param] = abs_paths or None
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
    stem = _safe_upload_stem(upload.name, fallback="upload")
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
        resolve_excel_sheet_for_company,
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
            use_sheet = sheet
            if use_sheet is None:
                use_sheet = resolve_excel_sheet_for_company(
                    path, active_company, locale=ui_locale
                )
            df = read_input_file(path, sheet_name=use_sheet, locale=ui_locale)
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
                sheet = use_sheet

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
