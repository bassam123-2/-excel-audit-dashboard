"""Arabic compliance dashboard — filter/summary/aging engine (Python port of JS logic)."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any

from .schema import BLANK, CANONICAL_NAMES

COL_YEAR = CANONICAL_NAMES["year"]
COL_TARGET = CANONICAL_NAMES["target_date"]
COL_MODIFIED = CANONICAL_NAMES["modified_date"]
COL_STATUS = CANONICAL_NAMES["status"]
COL_RESIDUAL = CANONICAL_NAMES["residual"]
COL_LEGAL = CANONICAL_NAMES["legal_text"]

PARAM_TO_COL: dict[str, str] = {
    "inherent": CANONICAL_NAMES["inherent"],
    "residual": COL_RESIDUAL,
    "status": COL_STATUS,
    "year": COL_YEAR,
    "department": CANONICAL_NAMES["department"],
    "legislator": CANONICAL_NAMES["legislator"],
    "system_name": CANONICAL_NAMES["system_name"],
    "authority": CANONICAL_NAMES["authority"],
    "regulation": CANONICAL_NAMES["regulation"],
    "legal_text": COL_LEGAL,
    "compliance_status": CANONICAL_NAMES["compliance_status"],
    "control_category": CANONICAL_NAMES["control_category"],
    "subsidiary_company": CANONICAL_NAMES["subsidiary_company"],
    "holding_company": CANONICAL_NAMES["holding_company"],
}

GROUP_DIMS = list(PARAM_TO_COL.values())

DETAIL_FIELDS: list[tuple[str, str]] = [
    ("email", "البريد الإلكتروني (email)"),
    (COL_STATUS, COL_STATUS),
    (COL_RESIDUAL, COL_RESIDUAL),
    (CANONICAL_NAMES["control_category"], CANONICAL_NAMES["control_category"]),
    (COL_TARGET, COL_TARGET),
    (COL_MODIFIED, COL_MODIFIED),
    (CANONICAL_NAMES["task_owner"], CANONICAL_NAMES["task_owner"]),
    (CANONICAL_NAMES["responsible_person"], CANONICAL_NAMES["responsible_person"]),
    (CANONICAL_NAMES["corrective_plan"], CANONICAL_NAMES["corrective_plan"]),
    ("ملاحظات الإدارة.1", CANONICAL_NAMES["mgmt_notes"]),
    (CANONICAL_NAMES["compliance_notes"], CANONICAL_NAMES["compliance_notes"]),
]

AGING_CONFIG: dict[str, Any] = {
    "risk_columns": [
        {"id": "very_low", "label": "متدني"},
        {"id": "low", "label": "منخفض"},
        {"id": "medium", "label": "متوسط"},
        {"id": "high", "label": "مرتفع"},
        {"id": "very_high", "label": "مرتفع جدا"},
        {"id": "other", "label": "أخرى"},
    ],
    "time_rows": [
        {"id": "not_due", "label": "لم يحن بعد"},
        {"id": "lt_6m", "label": "أقل من 6 أشهر"},
        {"id": "lt_1y", "label": "6 أشهر – سنة"},
        {"id": "ge_1y", "label": "أكثر من سنة"},
    ],
}

AUDIT_COLUMNS = [
    CANONICAL_NAMES["department"],
    CANONICAL_NAMES["legislator"],
    CANONICAL_NAMES["system_name"],
    CANONICAL_NAMES["authority"],
    CANONICAL_NAMES["regulation"],
]


def norm_nfkc(s: Any) -> str:
    return unicodedata.normalize("NFKC", str(s or ""))


def row_value(row: dict[str, str], col: str) -> str:
    v = row.get(col)
    if v is None or v == "":
        return BLANK
    return str(v)


def selected_from_params(params: dict[str, list[str]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for param, col in PARAM_TO_COL.items():
        vals = params.get(param, [])
        out[col] = [str(v).strip() for v in vals if str(v).strip()]
    return out


def apply_filters(
    rows: list[dict[str, str]],
    selected: dict[str, list[str]],
    skip_col: str | None = None,
) -> list[dict[str, str]]:
    def match(row: dict[str, str]) -> bool:
        for col, vals in selected.items():
            if col == skip_col or not vals:
                continue
            if row_value(row, col) not in vals:
                return False
        return True

    return [r for r in rows if match(r)]


def sort_group(key: str, values: list[str]) -> list[str]:
    if key == COL_YEAR:
        numeric = sorted([v for v in values if re.fullmatch(r"\d+", v)], key=int)
        rest = sorted(
            [v for v in values if not re.fullmatch(r"\d+", v) and v != BLANK],
            key=lambda x: x,
        )
        if BLANK in values:
            return [BLANK, *numeric, *rest]
        return [*numeric, *rest]
    return sorted(values, key=lambda x: x)


def build_summary(
    rows: list[dict[str, str]], selected: dict[str, list[str]]
) -> dict[str, Any]:
    fully = apply_filters(rows, selected, None)
    available_dims = [dim for dim in GROUP_DIMS if any(dim in r for r in rows)]
    groups: dict[str, list[dict[str, Any]]] = {}
    for dim in available_dims:
        counts: dict[str, int] = {}
        for r in apply_filters(rows, selected, dim):
            k = row_value(r, dim)
            counts[k] = counts.get(k, 0) + 1
        ordered = sort_group(dim, list(counts.keys()))
        groups[dim] = [
            {"key": k, "label": k, "count": counts[k]} for k in ordered
        ]
    company_columns = {
        "holding": CANONICAL_NAMES["holding_company"] in available_dims,
        "subsidiary": CANONICAL_NAMES["subsidiary_company"] in available_dims,
    }
    return {
        "total": len(fully),
        "selected": selected,
        "groups": groups,
        "company_columns": company_columns,
    }


def pick_best_legal_row(matches: list[dict[str, str]]) -> dict[str, str] | None:
    if not matches:
        return None
    with_mail = [r for r in matches if row_value(r, "email") != BLANK]
    pool = with_mail or matches
    best = pool[0]
    best_score = -1
    for r in pool:
        score = sum(1 for col, _ in DETAIL_FIELDS if row_value(r, col) != BLANK)
        if score > best_score:
            best_score = score
            best = r
    return best


def legal_details_from_rows(
    rows: list[dict[str, str]], text: str
) -> dict[str, Any] | None:
    matches = [r for r in rows if row_value(r, COL_LEGAL) == text]
    row = pick_best_legal_row(matches)
    if not row:
        return None
    fields = [
        {"label": label, "value": row_value(row, col)}
        for col, label in DETAIL_FIELDS
    ]
    em = row_value(row, "email")
    recipient = em if em != BLANK else ""
    excel_row = rows.index(row) + 2 if row in rows else 0
    return {
        "legal_text": text,
        "excel_row": excel_row,
        "picked_row_index": 0,
        "recipient_email": recipient,
        "fields": fields,
        "images": [],
    }


def is_open_status_for_aging(status_text: str) -> bool:
    t = norm_nfkc(status_text).replace("\u00a0", " ")
    t = re.sub(r"\s+", " ", t)
    if "مفتوح" not in t:
        return False
    if "تجاوز" in t and "تاريخ" in t and "التصحيح" in t:
        return True
    if "ضمن" in t and "تاريخ" in t and "التصحيح" in t:
        return True
    return False


def aging_risk_key(residual_norm: str) -> str | None:
    if residual_norm == BLANK:
        return None
    t = norm_nfkc(residual_norm).replace("\u00a0", " ").strip()
    t = re.sub(r"\s+", " ", t)
    for bad, good in [
        ("مرنفع", "مرتفع"),
        ("مرتفغ", "مرتفع"),
        ("مرتفاع", "مرتفع"),
        ("مرنفغ", "مرتفع"),
        ("مرتفغ جدا", "مرتفع جدا"),
    ]:
        t = t.replace(bad, good)
    if "متدني" in t and re.search(r"انخفاض|انخفاظ|انخغاض|انخفاق", t):
        return "very_low"
    if ("جدا" in t or "جداً" in t or "جدآ" in t) and ("مرتفع" in t or "مرفع" in t):
        return "very_high"
    if "متوسط" in t:
        return "medium"
    if "منخفض" in t and "متدني" not in t:
        return "low"
    if "مرتفع" in t or "مرفع" in t:
        return "high"
    return None


def parse_date_at_noon(dstr: str) -> date | None:
    if not dstr or dstr == BLANK:
        return None
    try:
        if "T" in dstr:
            return datetime.fromisoformat(dstr.replace("Z", "")).date()
        return datetime.strptime(dstr[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def aging_time_bucket(compare: date, reference: date) -> str | None:
    if compare > reference:
        return "not_due"
    overdue_days = (reference - compare).days
    if overdue_days < 183:
        return "lt_6m"
    if overdue_days < 365:
        return "lt_1y"
    return "ge_1y"


def compute_aging(
    rows: list[dict[str, str]],
    selected: dict[str, list[str]],
    reference_raw: str,
    date_source: str = "target",
) -> dict[str, Any]:
    ref = parse_date_at_noon(reference_raw)
    if not ref:
        return {"error": "Invalid reference date"}
    date_col = COL_MODIFIED if date_source == "modified" else COL_TARGET
    cfg = AGING_CONFIG
    risk_keys = [x["id"] for x in cfg["risk_columns"]]
    matrix: dict[str, dict[str, int]] = {
        tr["id"]: {rk: 0 for rk in risk_keys} for tr in cfg["time_rows"]
    }
    skipped_other = 0
    unknown_time = 0
    for row in apply_filters(rows, selected, None):
        st = row_value(row, COL_STATUS)
        if not is_open_status_for_aging(st):
            skipped_other += 1
            continue
        rkey = aging_risk_key(row_value(row, COL_RESIDUAL)) or "other"
        cdt = parse_date_at_noon(row_value(row, date_col))
        if not cdt:
            unknown_time += 1
            continue
        tkey = aging_time_bucket(cdt, ref)
        if not tkey or tkey not in matrix:
            unknown_time += 1
            continue
        matrix[tkey][rkey] = matrix[tkey].get(rkey, 0) + 1

    time_rows = []
    for tr in cfg["time_rows"]:
        cells = matrix.get(tr["id"], {})
        total = sum(cells.get(k, 0) for k in risk_keys)
        time_rows.append({"id": tr["id"], "label": tr["label"], "cells": cells, "total": total})

    column_totals = {k: 0 for k in risk_keys}
    for tr in time_rows:
        for k in risk_keys:
            column_totals[k] += tr["cells"].get(k, 0)
    grand_total = sum(column_totals.values())

    return {
        "reference": reference_raw,
        "date_source": date_source,
        "risk_columns": cfg["risk_columns"],
        "time_rows": time_rows,
        "column_totals": column_totals,
        "grand_total": grand_total,
        "skipped_other_status": skipped_other,
        "skipped_unknown_time": unknown_time,
    }


def build_audit_plan_panel(
    rows: list[dict[str, str]], selected: dict[str, list[str]]
) -> dict[str, Any]:
    filtered = apply_filters(rows, selected, None)
    columns = []
    for col in AUDIT_COLUMNS:
        counts: dict[str, int] = {}
        non_null = 0
        for r in filtered:
            v = row_value(r, col)
            counts[v] = counts.get(v, 0) + 1
            if v != BLANK:
                non_null += 1
        ordered = sorted(counts.items(), key=lambda x: -x[1])
        columns.append(
            {
                "name": col,
                "entries": [{"label": k, "count": c} for k, c in ordered[:80]],
                "truncated": len(ordered) > 80,
                "distinct": len(ordered),
                "non_null": non_null,
            }
        )
    return {"total_rows": len(filtered), "columns": columns}


def build_snapshot_pack(
    rows: list[dict[str, str]],
    *,
    brand_logos: dict[str, str] | None = None,
    default_brand_code: str | None = None,
    legal_details: dict[str, Any] | None = None,
    row_images: dict[str, list] | None = None,
) -> dict[str, Any]:
    return {
        "rows": rows,
        "aging_config": AGING_CONFIG,
        "audit_columns": AUDIT_COLUMNS,
        "brand_logos": brand_logos or {},
        "default_brand_code": default_brand_code,
        "legal_details": legal_details or {},
        "row_images": row_images or {},
    }


def parse_query_params(query_dict) -> dict[str, list[str]]:
    """Parse Django QueryDict into param lists for selected_from_params."""
    params: dict[str, list[str]] = {}
    for key in PARAM_TO_COL:
        params[key] = query_dict.getlist(key)
    return params
