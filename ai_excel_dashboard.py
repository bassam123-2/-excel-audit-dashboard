#!/usr/bin/env python3
"""Dynamic Excel dashboard: validation, charts, and export-ready summaries.

Main engine: audit payload, HTML/JS report, SMTP helpers.
See START_HERE.md, docs/FOLDER_MAP.md, docs/ARCHITECTURE.md."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import math
import mimetypes
import numbers
import os
import re
import smtplib
import ssl
import subprocess
import sys
import uuid
import zipfile
from datetime import datetime
from email.utils import formataddr
from email.header import Header
from email.mime.text import MIMEText
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

from dashboard_locale import AR_MONTH_HINTS, normalize_locale, tr
from data_io import ATTR_READ_NOTES, read_input_file
from site_robots import ROBOTS_META_HTML

REPORT_VERSION = "dashboard-v1.0.4"
ALL_ATTACHMENT_KINDS = frozenset(
    {
        "deck",
        "highRisk",
        "tgaViolations",
        "missingVehicle",
        "internalAuditQuarterly",
        "specialAssignment",
    }
)
_ATTACHMENT_TOGGLE_SPECS = (
    ("deck", "audit-deck-attach-cb", "audit-deck-attach-label"),
    ("highRisk", "audit-high-risk-cb", "audit-high-risk-label"),
    ("tgaViolations", "audit-tga-violations-cb", "audit-tga-violations-label"),
    ("missingVehicle", "audit-missing-vehicle-cb", "audit-missing-vehicle-label"),
    (
        "internalAuditQuarterly",
        "audit-internal-audit-quarterly-cb",
        "audit-internal-audit-quarterly-label",
    ),
    ("specialAssignment", "audit-special-assignment-cb", "audit-special-assignment-label"),
)
# Injected into generated HTML; replaced with Django API URLs via report_generation.inject_web_mail_api.
_MAIL_API_MARKER = "window.__AI_EXCEL_MAIL_API__=null;"
_PLAN_PARSE_API_MARKER = "window.__AI_EXCEL_PLAN_PARSE_URL__=null;"
_SMTP_HELPER_HOST = "127.0.0.1"
_SMTP_HELPER_PORT = 51977
_MAIL_API_FALLBACK_MARKER = (
    f'window.__AI_EXCEL_MAIL_API_FALLBACKS__=["http://127.0.0.1:{_SMTP_HELPER_PORT}/api/send-obs-email","http://localhost:{_SMTP_HELPER_PORT}/api/send-obs-email"];'
)
_DASHBOARD_ROOT = Path(__file__).resolve().parent


def detect_brand_logo_data_uri() -> str:
    """Try loading a dashboard logo and return it as an inline data URI."""
    candidates: list[Path] = []
    env_logo = os.getenv("DASHBOARD_LOGO_PATH", "").strip()
    if env_logo:
        candidates.append(Path(env_logo))
    candidates.extend(
        [
            _DASHBOARD_ROOT / "assets" / "aagh_logo.png",
            _DASHBOARD_ROOT / "assets" / "logo.png",
            _DASHBOARD_ROOT / "assets" / "brand_logo.png",
            _DASHBOARD_ROOT / "assets" / "company_logo.png",
            Path("logo.png"),
            Path("brand_logo.png"),
            Path("company_logo.png"),
            Path("assets/logo.png"),
            Path("assets/brand_logo.png"),
            Path("assets/company_logo.png"),
        ]
    )
    for p in candidates:
        try:
            if not p.exists() or not p.is_file():
                continue
            raw = p.read_bytes()
            if not raw:
                continue
            mime = mimetypes.guess_type(str(p))[0] or "image/png"
            b64 = base64.b64encode(raw).decode("ascii")
            return f"data:{mime};base64,{b64}"
        except Exception:
            continue
    return ""


_LOGO_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"})
_CASE_SENSITIVE_LOGO_CODES = frozenset({"nat", "aum", "saco", "autostar", "btc"})


def _norm_logo_key(label: str) -> str:
    s = str(label or "").strip().casefold()
    s = re.sub(r"[^\w\s\u0600-\u06ff.-]+", "", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def _logo_catalog_company_key(stem: str) -> str:
    raw = str(stem or "").strip()
    if raw in _CASE_SENSITIVE_LOGO_CODES:
        return raw
    return _norm_logo_key(raw)


def _path_to_logo_data_uri(path: Path) -> str | None:
    try:
        if not path.exists() or not path.is_file():
            return None
        raw = path.read_bytes()
        if not raw:
            return None
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception:
        return None


def _company_logo_catalog_roots() -> list[Path]:
    roots: list[Path] = []
    env_dir = os.getenv("DASHBOARD_LOGOS_DIR", "").strip()
    if env_dir:
        roots.append(Path(env_dir).expanduser())
    try:
        roots.append(Path.cwd().resolve() / "assets" / "logos")
    except Exception:
        pass
    roots.append(_DASHBOARD_ROOT / "assets" / "logos")
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _build_filesystem_logo_catalog() -> dict[str, Any]:
    """Scan assets/logos/ for legacy/fallback logo mappings."""
    default_uri = detect_brand_logo_data_uri()
    companies: dict[str, str] = {}
    subcompanies: dict[str, str] = {}

    def ingest_file(path: Path, company_key: str | None, sub_key: str | None) -> None:
        uri = _path_to_logo_data_uri(path)
        if not uri:
            return
        stem_norm = _norm_logo_key(path.stem)
        if stem_norm in ("default", "_default", "fallback"):
            nonlocal default_uri
            default_uri = uri
            return
        if sub_key is not None and company_key is not None:
            subcompanies[f"{company_key}|{sub_key}"] = uri
            return
        if company_key is not None:
            companies[company_key] = uri

    for logos_dir in _company_logo_catalog_roots():
        try:
            if not logos_dir.is_dir():
                continue
            for entry in sorted(logos_dir.iterdir(), key=lambda p: p.name.lower()):
                if entry.is_file() and entry.suffix.lower() in _LOGO_IMAGE_EXTS:
                    ingest_file(entry, _logo_catalog_company_key(entry.stem), None)
                elif entry.is_dir():
                    co_key = _logo_catalog_company_key(entry.name)
                    if not co_key:
                        continue
                    for sub_entry in sorted(entry.iterdir(), key=lambda p: p.name.lower()):
                        if sub_entry.is_file() and sub_entry.suffix.lower() in _LOGO_IMAGE_EXTS:
                            ingest_file(
                                sub_entry,
                                co_key,
                                _logo_catalog_company_key(sub_entry.stem),
                            )
        except Exception:
            continue

    if default_uri:
        for alias in (
            "abdullatif alissa group holding co",
            "abdullatif alissa group holding co.",
            "abdullatif alissa group",
            "aagh",
            "شركة مجموعة عبداللطيف العيسى القابضة",
        ):
            key = _norm_logo_key(alias)
            if key and key not in companies:
                companies[key] = default_uri

    for key, uri in list(companies.items()):
        if key in _CASE_SENSITIVE_LOGO_CODES:
            upper = key.upper()
            if upper not in companies:
                companies[upper] = uri

    return {
        "default": default_uri or "",
        "companies": companies,
        "subcompanies": subcompanies,
        "caseSensitiveCodes": sorted(_CASE_SENSITIVE_LOGO_CODES),
    }


def _filefield_to_logo_data_uri(file_field) -> str | None:
    if not file_field:
        return None
    try:
        return _path_to_logo_data_uri(Path(file_field.path))
    except Exception:
        return None


def _register_company_logo_keys(
    companies: dict[str, str],
    subcompanies: dict[str, str],
    company_obj,
    uri: str,
    *,
    parent_key: str | None = None,
) -> None:
    from audit_app.models import COMPANY_KIND_SUBSIDIARY

    keys = {_logo_catalog_company_key(company_obj.code)}
    keys.add(_logo_catalog_company_key(company_obj.name))
    for label in company_obj.accepted_excel_names():
        keys.add(_logo_catalog_company_key(label))
    keys.discard("")
    if company_obj.company_kind == COMPANY_KIND_SUBSIDIARY and parent_key:
        sub_key = _logo_catalog_company_key(company_obj.code)
        if sub_key:
            subcompanies[f"{parent_key}|{sub_key}"] = uri
    for key in keys:
        if key:
            companies[key] = uri
        if key in _CASE_SENSITIVE_LOGO_CODES:
            companies[key.upper()] = uri


def build_company_logo_catalog(company_entity=None) -> dict[str, Any]:
    """Map company / subcompany labels to embedded logo data URIs."""
    catalog = _build_filesystem_logo_catalog()
    if company_entity is None:
        return catalog

    from audit_app.company_access import active_subsidiaries_of, tenant_root

    companies: dict[str, str] = dict(catalog.get("companies") or {})
    subcompanies: dict[str, str] = dict(catalog.get("subcompanies") or {})
    default_uri = catalog.get("default") or ""

    root = tenant_root(company_entity)
    root_uri = _filefield_to_logo_data_uri(root.logo) if root.logo else ""
    if root_uri:
        default_uri = root_uri
        _register_company_logo_keys(companies, subcompanies, root, root_uri)
        parent_key = _logo_catalog_company_key(root.code)
        for sub in active_subsidiaries_of(root):
            sub_uri = _filefield_to_logo_data_uri(sub.logo) if sub.logo else root_uri
            if sub_uri:
                _register_company_logo_keys(
                    companies,
                    subcompanies,
                    sub,
                    sub_uri,
                    parent_key=parent_key,
                )

    return {
        "default": default_uri or catalog.get("default") or "",
        "companies": companies,
        "subcompanies": subcompanies,
        "caseSensitiveCodes": sorted(_CASE_SENSITIVE_LOGO_CODES),
    }

def content_fingerprint(df: pd.DataFrame, source_name: str) -> str:
    """Stable hash of file name + schema + cell data so each dataset gets a unique identity."""
    h = hashlib.sha256()
    h.update(source_name.encode("utf-8", errors="replace"))
    h.update(json.dumps([str(c) for c in df.columns]).encode())
    h.update(f"{df.shape[0]}x{df.shape[1]}".encode())
    cells = df.shape[0] * df.shape[1]
    if cells > 500_000:
        h.update(df.head(4000).to_csv(index=False).encode("utf-8", errors="replace"))
        h.update(df.tail(4000).to_csv(index=False, header=False).encode("utf-8", errors="replace"))
        for c in df.columns:
            s = pd.to_numeric(df[c], errors="coerce")
            if s.notna().any():
                h.update(f"{c}:{float(s.sum(skipna=True)):.6f}".encode())
    else:
        h.update(df.to_csv(index=False).encode("utf-8", errors="replace"))
    return h.hexdigest()


def theme_from_fingerprint(fp_hex: str) -> dict[str, int]:
    """Derive distinct HSL hues from fingerprint (each file → different palette)."""
    n = int(fp_hex[:12], 16)
    h1 = n % 360
    h2 = (h1 + 32 + ((n >> 10) % 72)) % 360
    h3 = (h2 + 48 + ((n >> 20) % 48)) % 360
    return {"h1": h1, "h2": h2, "h3": h3}


def infer_month_order(series: pd.Series) -> list[str] | None:
    month_order = [
        "jan", "feb", "mar", "apr", "may", "jun",
        "jul", "aug", "sep", "oct", "nov", "dec",
    ]
    full_names = {
        "jan": "january", "feb": "february", "mar": "march", "apr": "april",
        "may": "may", "jun": "june", "jul": "july", "aug": "august",
        "sep": "september", "oct": "october", "nov": "november", "dec": "december",
    }
    values = series.astype(str).str.strip().unique().tolist()
    values = [v for v in values if v and str(v).lower() != "nan"]
    if not values:
        return None
    present: list[str] = []
    for m in month_order:
        full = full_names[m]
        for v in values:
            if v in present:
                continue
            vl = v.lower()
            matched = vl == m or vl.startswith(m) or vl == full
            if not matched:
                for ar, mk in AR_MONTH_HINTS:
                    if mk == m and ar in v:
                        matched = True
                        break
            if matched:
                present.append(v)
                break
    if len(present) >= 3:
        ordered: list[str] = []
        for p in present:
            if p not in ordered:
                ordered.append(p)
        return ordered
    return None


def numeric_columns(df: pd.DataFrame) -> list[str]:
    cols: list[str] = []
    for c in df.columns:
        s = pd.to_numeric(df[c], errors="coerce")
        if s.notna().sum() > 0:
            cols.append(str(c))
    return cols


def detect_primary_columns(df: pd.DataFrame) -> dict[str, str | None]:
    num_cols = numeric_columns(df)
    cat_cols = [c for c in categorical_columns(df) if c not in num_cols]
    out: dict[str, str | None] = {
        "revenue": None,
        "sales": None,
        "profit": None,
        "cost": None,
        "period": None,
        "segment": None,
    }
    lat_rev = ("revenue", "income", "turnover")
    ar_rev = ("إيرادات", "إيراد", "دخل", "الإيرادات")
    lat_sales = ("sales",)
    ar_sales = ("مبيعات", "المبيعات", "مبيعة")
    lat_profit = ("profit", "margin")
    ar_profit = ("ربح", "أرباح", "الربح", "هامش", "هامش الربح")
    lat_cost = ("cost", "expense", "opex", "cogs")
    ar_cost = ("تكلفة", "التكلفة", "مصروف", "مصروفات", "نفقات", "نفقة")
    lat_period = ("month", "date", "week", "quarter", "year", "period")
    ar_period = ("شهر", "تاريخ", "أسبوع", "ربع", "سنة", "فترة", "الشهر", "التاريخ", "السنة")
    lat_seg = ("region", "department", "category", "product", "owner", "team", "entity")
    ar_seg = ("منطقة", "قسم", "فئة", "منتج", "مالك", "فريق", "الجهة", "إقليم", "المنطقة", "القسم")

    for c in num_cols:
        raw = str(c).strip()
        n = raw.lower()
        if out["revenue"] is None and (
            any(k in n for k in lat_rev) or any(k in raw for k in ar_rev)
        ):
            out["revenue"] = c
        if out["sales"] is None and (
            any(k in n for k in lat_sales) or any(k in raw for k in ar_sales)
        ):
            out["sales"] = c
        if out["profit"] is None and (
            any(k in n for k in lat_profit) or any(k in raw for k in ar_profit)
        ):
            out["profit"] = c
        if out["cost"] is None and (
            any(k in n for k in lat_cost) or any(k in raw for k in ar_cost)
        ):
            out["cost"] = c
    for c in df.columns:
        raw = str(c).strip()
        n = raw.lower()
        if out["period"] is None and (
            any(k in n for k in lat_period) or any(k in raw for k in ar_period)
        ):
            out["period"] = str(c)
    for c in cat_cols:
        raw = str(c).strip()
        n = raw.lower()
        if out["segment"] is None and (
            any(k in n for k in lat_seg) or any(k in raw for k in ar_seg)
        ):
            out["segment"] = c
    if out["segment"] is None and cat_cols:
        out["segment"] = cat_cols[0]
    return out


SYNTHETIC_SEGMENT_COL = "__dashboard_segment__"
SYNTHETIC_PERIOD_ROW = "__dashboard_period_row__"


def _metric_skip_set(detected: dict[str, Any]) -> set[str]:
    return {
        str(x)
        for x in (
            detected.get("revenue"),
            detected.get("sales"),
            detected.get("profit"),
            detected.get("cost"),
        )
        if x is not None and str(x).strip() != ""
    }


def infer_period_column_from_values(
    df: pd.DataFrame, detected: dict[str, str | None]
) -> str | None:
    """Pick the column that best looks like a time axis (values + optional name hints)."""
    skip = _metric_skip_set(detected)
    best_col: str | None = None
    best_score = -1.0
    n = len(df)
    if n < 1:
        return None
    lat_hint = (
        "month", "date", "week", "quarter", "year", "period", "time", "day",
        "fy", "semester", "trimester",
    )
    ar_hint = (
        "شهر", "تاريخ", "أسبوع", "ربع", "سنة", "فترة", "الشهر", "التاريخ",
        "السنة", "زمن", "وقت", "ايام", "أيام",
    )
    for c in df.columns:
        c_str = str(c).strip()
        if c_str in skip:
            continue
        s = df[c]
        non_null = s.dropna()
        m = int(non_null.shape[0])
        if m < 2:
            continue
        score = 0.0
        low = c_str.lower()
        if any(h in low for h in lat_hint) or any(h in c_str for h in ar_hint):
            score += 52.0

        as_str = non_null.astype(str).str.strip()
        dt = pd.to_datetime(as_str, errors="coerce", format="mixed")
        rate = float(dt.notna().sum()) / float(max(m, 1))
        if rate >= 0.32:
            score += rate * 72.0
            yy = dt.dt.year.dropna()
            if len(yy) and (int(yy.min()) < 1970 or int(yy.max()) > 2100):
                score -= 38.0

        num = pd.to_numeric(s, errors="coerce")
        nm = float(num.notna().sum()) / float(max(m, 1))
        if nm >= 0.82:
            nn = num.dropna()
            if len(nn) and float(((nn >= 1990) & (nn <= 2100)).mean()) >= 0.82:
                score += 50.0
            elif len(nn) and float(((nn >= 35000) & (nn <= 55000)).mean()) >= 0.22:
                score += 40.0
            med_abs = float(nn.abs().median()) if len(nn) else 0.0
            if med_abs > 1e8:
                score -= 35.0

        if infer_month_order(s) is not None:
            score += 36.0
        else:
            nu = int(non_null.nunique())
            if 2 <= nu <= min(400, max(3, n)):
                if s.dtype == object or pd.api.types.is_string_dtype(s):
                    score += 16.0

        if score > best_score:
            best_score = score
            best_col = c_str

    if best_col is not None and best_score >= 20.0:
        return best_col
    return None


def infer_segment_column_from_values(
    df: pd.DataFrame, detected: dict[str, str | None]
) -> str | None:
    """Pick a low-cardinality label column; never the period column."""
    period = detected.get("period")
    p_str = str(period).strip() if period is not None else ""
    skip = _metric_skip_set(detected)
    nums = set(numeric_columns(df))
    cats = categorical_columns(df)
    for c in cats:
        cs = str(c).strip()
        if cs == p_str or cs in skip:
            continue
        return cs
    for c in df.columns:
        cs = str(c).strip()
        if cs == p_str or cs in skip:
            continue
        if c in nums:
            continue
        s = df[c]
        nu = int(s.nunique(dropna=True))
        if 1 < nu <= min(120, max(2, len(df))):
            return cs
    return None


def build_detected_profile(df: pd.DataFrame) -> dict[str, Any]:
    """Name-based detection plus per-file value heuristics; always sets period & segment."""
    d: dict[str, Any] = dict(detect_primary_columns(df))
    d["_meta_inferred_period"] = False
    d["_meta_row_order_period"] = False
    d["_meta_inferred_segment"] = False
    d["_meta_synthetic_segment"] = False

    if d.get("period") is None:
        guess = infer_period_column_from_values(df, d)
        if guess:
            d["period"] = guess
            d["_meta_inferred_period"] = True
        else:
            d["period"] = SYNTHETIC_PERIOD_ROW
            d["_meta_row_order_period"] = True

    if d.get("segment") is None:
        seg_guess = infer_segment_column_from_values(df, d)
        if seg_guess:
            d["segment"] = seg_guess
            d["_meta_inferred_segment"] = True
        else:
            d["segment"] = SYNTHETIC_SEGMENT_COL
            d["_meta_synthetic_segment"] = True

    return d


def apply_dashboard_column_fallbacks(
    df: pd.DataFrame,
    detected: dict[str, Any],
    *,
    locale: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Add synthetic columns when we fell back to row order or a single segment bucket."""
    loc = normalize_locale(locale)
    out = df.copy()
    d = dict(detected)
    if d.get("_meta_row_order_period"):
        c = str(d["period"])
        out[c] = [f"#{i + 1}" for i in range(len(out))]
    if d.get("_meta_synthetic_segment"):
        c = str(d["segment"])
        out[c] = tr(loc, "val_overall")
    return out, d


def detected_for_engine(d: dict[str, Any]) -> dict[str, str | None]:
    return {
        "revenue": d.get("revenue"),
        "sales": d.get("sales"),
        "profit": d.get("profit"),
        "cost": d.get("cost"),
        "period": d.get("period"),
        "segment": d.get("segment"),
    }


def _quarter_from_month_label(val: str) -> str:
    s = str(val).strip().lower()
    if not s or s == "nan":
        return "Other"
    q_groups = (
        (("jan", "feb", "mar", "1", "q1"), "Q1"),
        (("apr", "may", "jun", "4", "q2"), "Q2"),
        (("jul", "aug", "sep", "7", "q3"), "Q3"),
        (("oct", "nov", "dec", "10", "q4"), "Q4"),
    )
    for keys, qlabel in q_groups:
        if any(k in s[:6] for k in keys if len(k) > 1) or s in keys:
            return qlabel
    if "q1" in s:
        return "Q1"
    if "q2" in s:
        return "Q2"
    if "q3" in s:
        return "Q3"
    if "q4" in s:
        return "Q4"
    return "Other"


def _detect_finance_category_column(df: pd.DataFrame, detected: dict[str, str | None]) -> str | None:
    period_col = detected.get("period")
    rev_c = detected.get("revenue") or detected.get("sales")
    skip = {c for c in (period_col, rev_c, detected.get("cost"), detected.get("profit")) if c}
    for c in df.columns:
        if c in skip:
            continue
        n = str(c).lower()
        if any(
            k in n
            for k in (
                "category",
                "department",
                "cost_center",
                "cost centre",
                "function",
                "division",
                "business_unit",
                "cost type",
                "channel",
            )
        ) or any(
            k in str(c)
            for k in (
                "فئة",
                "تصنيف",
                "قسم",
                "قناة",
                "وحدة",
            )
        ):
            return str(c)
    seg = detected.get("segment")
    if seg and seg not in skip:
        return str(seg)
    return None


def build_finance_trends_payload(
    df: pd.DataFrame,
    detected: dict[str, str | None],
    locale: str = "en",
) -> dict[str, Any]:
    """Long-format rows + metadata for client-side period/category aggregation."""
    loc = normalize_locale(locale)
    period_col = detected.get("period")
    rev_c = detected.get("revenue") or detected.get("sales")
    if not period_col or not rev_c:
        return {
            "available": False,
            "reason": tr(loc, "ft_need_time_revenue"),
        }

    exp_c = detected.get("cost")
    prof_c = detected.get("profit")
    cat_col = _detect_finance_category_column(df, detected)

    cols = [period_col, rev_c]
    if exp_c:
        cols.append(exp_c)
    if prof_c:
        cols.append(prof_c)
    if cat_col:
        cols.append(cat_col)
    ycol = None
    for c in df.columns:
        cs = str(c).strip()
        if str(c).lower() in ("year", "fiscal_year", "fy", "fiscal year") or "سنة" in cs:
            ycol = c
            if c not in cols:
                cols.append(c)
            break

    work = df[cols].copy()
    work[rev_c] = pd.to_numeric(work[rev_c], errors="coerce").fillna(0.0)
    exp_key = "__expenses__"
    if exp_c:
        work[exp_key] = pd.to_numeric(work[exp_c], errors="coerce").fillna(0.0)
    else:
        work[exp_key] = 0.0
    prof_key = "__profit__"
    if prof_c:
        work[prof_key] = pd.to_numeric(work[prof_c], errors="coerce").fillna(0.0)
    else:
        work[prof_key] = work[rev_c] - work[exp_key]

    lab = work[period_col].astype(str).str.strip()
    dt = pd.to_datetime(lab, errors="coerce", format="mixed")
    parsed_ok = int(dt.notna().sum()) >= max(1, len(work) // 2)
    # Bare month names (e.g. "Jan") can parse as year 0001 — treat as non-dates.
    if parsed_ok:
        years = dt.dt.year.dropna()
        if len(years) == 0 or int(years.min()) < 1970 or int(years.max()) > 2100:
            parsed_ok = False
    use_dt = bool(parsed_ok)

    if use_dt:
        work["_bm"] = dt.dt.strftime("%Y-%m")
        work["_bq"] = dt.dt.to_period("Q").astype(str)
        work["_by"] = dt.dt.year.astype(int).astype(str)
    else:
        work["_bm"] = lab
        work["_bq"] = lab.map(_quarter_from_month_label)
        if ycol:
            work["_by"] = work[ycol].astype(str).str.strip()
        else:
            work["_by"] = str(datetime.now().year)

    fcat = "__category__"
    uncat = tr(loc, "val_uncategorized")
    overall = tr(loc, "val_overall")
    if cat_col:
        work[fcat] = work[cat_col].fillna(uncat).astype(str).str.strip()
    else:
        work[fcat] = overall

    detail_rows: list[dict[str, Any]] = []
    for i in range(len(work)):
        r = work.iloc[i]
        detail_rows.append(
            {
                "month": str(r["_bm"]),
                "quarter": str(r["_bq"]),
                "year": str(r["_by"]),
                "category": str(r[fcat]),
                "revenue": round(float(r[rev_c]), 2),
                "expenses": round(float(r[exp_key]), 2),
                "profit": round(float(r[prof_key]), 2),
            }
        )

    cats = sorted({d["category"] for d in detail_rows})
    exp_disp = exp_c or tr(loc, "exp_none_zero")
    prof_disp = prof_c or tr(loc, "profit_computed", rev=rev_c)
    cat_disp = cat_col or tr(loc, "category_fallback")
    return {
        "available": True,
        "detail_rows": detail_rows,
        "categories": ["__ALL__"] + cats,
        "category_column": cat_disp,
        "hint_line": tr(
            loc,
            "ft_metrics_intro",
            rev=str(rev_c),
            exp=str(exp_disp),
            prof=str(prof_disp),
            cat=str(cat_disp),
        ),
        "metric_labels": {
            "revenue": rev_c,
            "expenses": exp_disp,
            "profit": prof_disp,
        },
    }


def validate_schema_finance(
    df: pd.DataFrame,
    locale: str = "en",
    *,
    detected: dict[str, str | None] | None = None,
) -> tuple[list[str], list[str]]:
    loc = normalize_locale(locale)
    errors: list[str] = []
    warnings: list[str] = []
    if df.shape[0] < 2:
        errors.append(tr(loc, "err_min_rows"))
    if df.shape[1] < 3:
        errors.append(tr(loc, "err_min_cols"))
    num_cols = numeric_columns(df)
    if not num_cols:
        errors.append(tr(loc, "err_no_numeric"))
    elif len(num_cols) < 2:
        warnings.append(tr(loc, "warn_one_numeric"))
    if detected is None:
        prof = build_detected_profile(df)
        df_adj, prof = apply_dashboard_column_fallbacks(df, prof, locale=loc)
        detected = detected_for_engine(prof)
        df = df_adj
    if detected.get("period") is None:
        errors.append(tr(loc, "err_no_period"))
    if detected.get("segment") is None:
        errors.append(tr(loc, "err_no_segment"))
    if detected.get("revenue") is None and detected.get("sales") is None:
        warnings.append(tr(loc, "warn_no_rev_name"))
    if detected.get("profit") is None:
        warnings.append(tr(loc, "warn_no_profit"))
    return errors, warnings


def categorical_columns(df: pd.DataFrame) -> list[str]:
    cols: list[str] = []
    for c in df.columns:
        nunique = df[c].nunique(dropna=True)
        if 1 < nunique <= 30:
            cols.append(str(c))
    return cols


def _json_safe_cell(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, numbers.Integral):
        return int(v)
    if isinstance(v, numbers.Real):
        fv = float(v)
        if math.isnan(fv):
            return None
        return fv
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (pd.Timestamp, datetime)):
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v)
    return str(v).strip()


def _json_safe_obs_date_cell(v: Any) -> Any:
    """Normalize observation date cells to ISO dates or Excel serials for aging."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.date().isoformat()
    if isinstance(v, numbers.Real) and not isinstance(v, bool):
        fv = float(v)
        if math.isnan(fv):
            return None
        if 1000 <= fv <= 80000:
            return int(fv) if fv == int(fv) else fv
        if fv >= 1e12:
            return datetime.utcfromtimestamp(fv / 1000.0).date().isoformat()
        if 1e9 <= fv < 1e12:
            return datetime.utcfromtimestamp(fv).date().isoformat()
        return fv
    if isinstance(v, numbers.Integral) and not isinstance(v, bool):
        if 1000 <= v <= 80000:
            return int(v)
        if v >= int(1e12):
            return datetime.utcfromtimestamp(v / 1000.0).date().isoformat()
        if int(1e9) <= v < int(1e12):
            return datetime.utcfromtimestamp(v).date().isoformat()
        return int(v)
    s = str(v).strip()
    if not s:
        return None
    dt = pd.to_datetime(s, errors="coerce", dayfirst=True)
    if pd.notna(dt):
        yr = int(dt.year)
        if 1970 <= yr <= 2100:
            return dt.date().isoformat()
    serial = pd.to_numeric(s, errors="coerce")
    if pd.notna(serial):
        sv = float(serial)
        if 1000 <= sv <= 80000:
            return int(sv) if sv == int(sv) else sv
    return s


def _filter_option_token(v: Any) -> str:
    """Stable string for filter dropdown values so they match _json_safe_cell rows after JSON parse."""
    j = _json_safe_cell(v)
    if j is None:
        return ""
    if isinstance(j, bool):
        return "true" if j else "false"
    if isinstance(j, int):
        return str(j)
    if isinstance(j, float):
        if j == int(j):
            return str(int(j))
        return str(j)
    return str(j).strip()


def _audit_observation_row_is_usable(row: pd.Series, colmap: dict[str, str]) -> bool:
    """Ignore trailing spacer rows (e.g. only IA Status filled, no year or observation)."""
    year = _filter_option_token(row[colmap["audit_year"]])
    obs = _filter_option_token(row[colmap["observation_name"]])
    return bool(year or obs)


def _raise_if_multiple_audit_companies(
    df: pd.DataFrame,
    audit_colmap: dict[str, str],
    *,
    locale: str,
) -> None:
    """Audit uploads with a Company column must list exactly one distinct company per file."""
    if "company" not in audit_colmap:
        return
    col = audit_colmap["company"]
    tokens = {
        _filter_option_token(x)
        for x in df[col].dropna().unique()
        if _filter_option_token(x) != ""
    }
    if len(tokens) <= 1:
        return
    loc = normalize_locale(locale)
    ordered = sorted(tokens, key=lambda x: (len(x), x))
    max_show = 12
    show = ordered[:max_show]
    names = ", ".join(show)
    if len(tokens) > max_show:
        names += tr(loc, "err_multiple_companies_trunc", n=len(tokens) - max_show)
    msg = tr(
        loc,
        "err_multiple_companies",
        col=str(col),
        count=len(tokens),
        names=names,
    )
    raise ValueError(tr(loc, "err_schema_prefix") + msg)


def _is_internal_dashboard_col(name: str) -> bool:
    s = str(name)
    return s.startswith("__") and (
        "dashboard" in s or s in (SYNTHETIC_SEGMENT_COL, SYNTHETIC_PERIOD_ROW)
    )


def _norm_audit_header(name: str) -> str:
    s = str(name).strip().lower()
    # Normalize separators and punctuation so headers like IA_Status / IA-Status map reliably.
    s = re.sub(r"[_/\-]+", " ", s)
    s = re.sub(r"[^a-z0-9\s#]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


AUDIT_OBS_ALIASES: dict[str, tuple[str, ...]] = {
    "audit_year": ("audit year", "year", "fy", "fiscal year"),
    "function": ("function", "business function"),
    "department": ("department", "dept", "business unit", "unit"),
    "audit_cycle": ("audit cycle/ department", "audit cycle / department", "audit cycle", "cycle"),
    "ia_status": ("ia status", "status", "internal audit status", "audit status"),
    "observation_name": ("observation name", "observation", "issue", "finding", "observation title"),
}

AUDIT_FILTER_SHORT = {
    "audit_year": "y",
    "function": "f",
    "department": "d",
    "audit_cycle": "c",
    "company": "co",
    "subcompany": "sco",
}

# Canonical observation-type order (matches standard audit workbook layout).
OBS_TYPE_CANONICAL_ORDER: tuple[str, ...] = (
    "Strategy",
    "Operation",
    "operation",
    "ERP System",
    "ERP system",
    "Policies & Procedures",
    "Authority Matrix & DoA",
    "Org. Structure & JD & KPI's",
    "Org. structure & JD & KPI's",
)


def _order_observation_types(file_order: list[str]) -> list[str]:
    """Preserve workbook order while preferring the canonical observation-type sequence."""
    used: set[str] = set()
    ordered: list[str] = []
    lower_to_actual = {v.lower(): v for v in file_order}
    for canon in OBS_TYPE_CANONICAL_ORDER:
        actual = lower_to_actual.get(canon.lower())
        if actual and actual not in used:
            ordered.append(actual)
            used.add(actual)
    for v in file_order:
        if v not in used:
            ordered.append(v)
            used.add(v)
    return ordered


def resolve_audit_observation_columns(df: pd.DataFrame) -> dict[str, str] | None:
    """Map audit register columns to logical roles. Function is optional; other core columns are required."""
    n2c = {_norm_audit_header(c): str(c) for c in df.columns}

    def pick(aliases: tuple[str, ...]) -> str | None:
        for a in aliases:
            na = _norm_audit_header(a)
            if na in n2c:
                return n2c[na]
        # Fuzzy fallback: all alias words must be present in header, ignoring short stopwords.
        stopwords = {"of", "the", "and", "a", "an"}
        for a in aliases:
            words = [w for w in _norm_audit_header(a).split() if w and w not in stopwords]
            if not words:
                continue
            for na, actual in n2c.items():
                if all(w in na for w in words):
                    return actual
        return None

    out: dict[str, str] = {}
    for key, aliases in AUDIT_OBS_ALIASES.items():
        col = pick(aliases)
        if col is None and key == "audit_cycle":
            for na, actual in n2c.items():
                if "audit cycle" in na and "department" in na:
                    col = actual
                    break
        if col is None and key == "ia_status":
            for na, actual in n2c.items():
                if "ia" in na and "status" in na:
                    col = actual
                    break
        if col is None:
            if key == "function":
                continue
            return None
        out[key] = col
    rcol = pick(("rating",))
    if rcol:
        out["rating"] = rcol
    otcol = pick(("observation type",))
    if otcol:
        out["observation_type"] = otcol
    cocol = pick(("company",))
    if cocol:
        out["company"] = cocol
    subcocol = pick(("subcompany", "sub company", "sub-company", "sub_company"))
    if subcocol:
        out["subcompany"] = subcocol
    sumcol = pick(("summary of observation", "observation summary"))
    if sumcol is None:
        for na, actual in n2c.items():
            if "summary" in na and "observation" in na:
                sumcol = actual
                break
    if sumcol is None:
        for na, actual in n2c.items():
            if na == "summary" or na.endswith(" summary"):
                sumcol = actual
                break
    recol = pick(("recommendation", "recommendations"))
    if recol is None:
        for na, actual in n2c.items():
            if "recommendation" in na:
                recol = actual
                break
    implduecol = pick(("implementation due date", "implementation due"))
    if implduecol is None:
        for na, actual in n2c.items():
            if "implementation" in na and "due" in na:
                implduecol = actual
                break
    if implduecol is None:
        for na, actual in n2c.items():
            if "impl" in na and "due" in na and "date" in na:
                implduecol = actual
                break
    targetdatecol = pick(("target date", "target completion date"))
    if targetdatecol is None:
        for na, actual in n2c.items():
            if (
                "target" in na
                and "date" in na
                and "implementation" not in na
                and "impl" not in na
            ):
                targetdatecol = actual
                break
    reviseddatecol = pick(("revised date", "revised completion date", "revised target date"))
    if reviseddatecol is not None:
        if not _norm_audit_header(reviseddatecol).startswith("revised date"):
            reviseddatecol = None
    if reviseddatecol is None:
        for na, actual in n2c.items():
            if na.startswith("revised date"):
                reviseddatecol = actual
                break
    obsidcol = pick(
        ("observation id", "observation no", "observation number", "obs id", "observation #")
    )
    if obsidcol is None:
        for na, actual in n2c.items():
            if "observation" in na and "id" in na and "observation name" not in na:
                obsidcol = actual
                break
    if sumcol:
        out["obs_summary"] = sumcol
    if recol:
        out["recommendation"] = recol
    if implduecol:
        out["implementation_due"] = implduecol
    if targetdatecol:
        out["target_date"] = targetdatecol
    if reviseddatecol:
        out["revised_date"] = reviseddatecol
    if obsidcol:
        out["observation_id"] = obsidcol
    emailcol = pick(("email", "e-mail", "e mail", "mail"))
    if emailcol is None:
        for na, actual in n2c.items():
            if na == "email" or "e-mail" in na or "email" in na:
                emailcol = actual
                break
    if emailcol is None:
        for na, actual in n2c.items():
            if "بريد" in na or "الإيميل" in na or "ايميل" in na:
                emailcol = actual
                break
    if emailcol:
        out["email"] = emailcol
    return out


def build_audit_observation_payload(
    df: pd.DataFrame,
    colmap: dict[str, str],
    *,
    locale: str,
    max_rows: int = 8000,
    max_options: int = 200,
) -> dict[str, Any]:
    loc = normalize_locale(locale)
    all_token = "__ALL__"
    df_obs = df[df.apply(lambda r: _audit_observation_row_is_usable(r, colmap), axis=1)]
    fk_order: list[str] = ["audit_year", "audit_cycle", "department"]
    has_co_dim = False
    if "company" in colmap:
        c_co = colmap["company"]
        co_tokens = {
            _filter_option_token(x)
            for x in df_obs[c_co].dropna().unique()
            if _filter_option_token(x) != ""
        }
        if co_tokens:
            fk_order.insert(0, "company")
            has_co_dim = True
    if "subcompany" in colmap:
        s_col = colmap["subcompany"]
        sc_tokens = {
            _filter_option_token(x)
            for x in df_obs[s_col].dropna().unique()
            if _filter_option_token(x) != ""
        }
        if sc_tokens:
            fk_order.insert(1 if has_co_dim else 0, "subcompany")
    filter_dims: list[dict[str, Any]] = []
    for logical in fk_order:
        c = colmap[logical]
        sub = df_obs[c]
        tokens = {
            _filter_option_token(x)
            for x in sub.dropna().unique()
            if _filter_option_token(x) != ""
        }
        vals = sorted(tokens, key=lambda x: (len(x), x))[:max_options]
        filter_dims.append(
            {
                "key": AUDIT_FILTER_SHORT[logical],
                "label": c,
                "values": vals,
            }
        )
    n_df = len(df_obs)
    clip = df_obs.iloc[:max_rows] if n_df > max_rows else df_obs
    has_rating = "rating" in colmap
    has_observation_type = "observation_type" in colmap
    obs_type_order: list[str] = []
    if has_observation_type:
        ot_s = df_obs[colmap["observation_type"]]
        file_order: list[str] = []
        seen_ot: set[str] = set()
        for x in ot_s.dropna().unique():
            tok = _filter_option_token(x)
            if tok and tok not in seen_ot:
                seen_ot.add(tok)
                file_order.append(tok)
        obs_type_order = _order_observation_types(file_order)[:80]
    rows_out: list[dict[str, Any]] = []
    for _, r in clip.iterrows():
        rec: dict[str, Any] = {
            "_idx": len(rows_out),
            "y": _json_safe_cell(r[colmap["audit_year"]]),
            "f": (
                _json_safe_cell(r[colmap["function"]])
                if "function" in colmap
                else None
            ),
            "d": _json_safe_cell(r[colmap["department"]]),
            "c": _json_safe_cell(r[colmap["audit_cycle"]]),
            "ia": _json_safe_cell(r[colmap["ia_status"]]),
            "obs": _json_safe_cell(r[colmap["observation_name"]]),
        }
        if "company" in colmap:
            rec["co"] = _json_safe_cell(r[colmap["company"]])
        if "subcompany" in colmap:
            rec["sco"] = _json_safe_cell(r[colmap["subcompany"]])
        if has_rating:
            rec["rt"] = _json_safe_cell(r[colmap["rating"]])
        else:
            rec["rt"] = None
        if has_observation_type:
            rec["ot"] = _json_safe_cell(r[colmap["observation_type"]])
        else:
            rec["ot"] = None
        if "obs_summary" in colmap:
            rec["osum"] = _json_safe_cell(r[colmap["obs_summary"]])
        else:
            rec["osum"] = None
        if "recommendation" in colmap:
            rec["rec"] = _json_safe_cell(r[colmap["recommendation"]])
        else:
            rec["rec"] = None
        if "implementation_due" in colmap:
            rec["idue"] = _json_safe_obs_date_cell(r[colmap["implementation_due"]])
        else:
            rec["idue"] = None
        if "target_date" in colmap:
            rec["tdate"] = _json_safe_obs_date_cell(r[colmap["target_date"]])
        else:
            rec["tdate"] = None
        if "revised_date" in colmap:
            rec["rdate"] = _json_safe_obs_date_cell(r[colmap["revised_date"]])
        else:
            rec["rdate"] = None
        if "observation_id" in colmap:
            rec["oid"] = _json_safe_cell(r[colmap["observation_id"]])
        else:
            rec["oid"] = None
        if "email" in colmap:
            rec["em"] = _json_safe_cell(r[colmap["email"]])
        else:
            rec["em"] = None
        rows_out.append(rec)
    loaded = len(clip)
    rating_types: list[dict[str, str]] = []
    if has_rating:
        for val, tr_key in (
            ("Critical", "audit_rating_critical"),
            ("High", "audit_rating_high"),
            ("Medium", "audit_rating_medium"),
            ("Low", "audit_rating_low"),
        ):
            rating_types.append({"value": val, "label": tr(loc, tr_key)})
    return {
        "available": True,
        "all_token": all_token,
        "filter_dims": filter_dims,
        "rows": rows_out,
        "has_rating": has_rating,
        "has_implementation_due": "implementation_due" in colmap,
        "has_target_date": "target_date" in colmap,
        "has_revised_date": "revised_date" in colmap,
        "has_observation_id": "observation_id" in colmap,
        "has_email": "email" in colmap,
        "has_observation_type": has_observation_type,
        "has_function": "function" in colmap,
        "has_subcompany": "subcompany" in colmap,
        "obs_type_order": obs_type_order,
        "rating_types": rating_types,
        "truncated": n_df > max_rows,
        "total_rows_in_file": n_df,
        "embedded_row_cap": max_rows,
        "ui": {
            "all": tr(loc, "audit_filter_all"),
            "filterDimSelectAll": tr(loc, "audit_filter_dim_select_all"),
            "filterDimDeselectAll": tr(loc, "audit_filter_dim_deselect_all"),
            "auditYearsTitle": tr(loc, "audit_year_strip_title"),
            "obsListHeading": tr(loc, "audit_obs_list_heading"),
            "obsListEmpty": tr(loc, "audit_obs_list_empty"),
            "iaStatusTpl": tr(loc, "audit_ia_status_tpl"),
            "heroBarPrefix": tr(loc, "audit_hero_bar_prefix"),
            "ratingTpl": tr(loc, "audit_rating_tpl"),
            "statusBlank": tr(loc, "audit_status_blank"),
            "truncatedHint": tr(
                loc, "audit_truncated_hint", loaded=loaded, total=n_df
            ),
            "ratingStripTitle": tr(loc, "audit_rating_strip_title"),
            "obsSelectHint": tr(loc, "audit_obs_select_hint"),
            "obsNoneForSelection": tr(loc, "audit_obs_none_for_selection"),
            "topBarAria": tr(loc, "audit_top_bar_aria"),
            "totalLabel": tr(loc, "audit_total_label"),
            "totalSubAll": tr(loc, "audit_total_sub_all"),
            "totalSubStatus": tr(loc, "audit_total_sub_status"),
            "totalSubStatuses": tr(loc, "audit_total_sub_statuses"),
            "totalCardAria": tr(loc, "audit_total_card_aria"),
            "boxRatingsAria": tr(loc, "audit_box_ratings_aria"),
            "boxObsAria": tr(loc, "audit_box_obs_aria"),
            "obsTypeBarTitle": tr(loc, "audit_obs_type_bar_title"),
            "boxObsTypeAria": tr(loc, "audit_box_obs_type_aria"),
            "boxYearsAria": tr(loc, "audit_box_years_aria"),
            "ratingTypesTotal": tr(loc, "audit_rating_types_total"),
            "obsTypeClickHint": tr(loc, "audit_obs_type_click_hint"),
            "obsNamesToggleHint": tr(loc, "audit_obs_names_toggle_hint"),
            "obsShowNamesCheckboxAria": tr(loc, "audit_obs_show_names_checkbox_aria"),
            "obsNamesMetaSelect": tr(loc, "audit_obs_names_meta_select"),
            "obsNamesMetaCount": tr(loc, "audit_obs_names_meta_count"),
            "obsNamesShowChecklist": tr(loc, "audit_obs_names_show_checklist"),
            "obsChecklistSelected": tr(loc, "audit_obs_checklist_selected"),
            "obsChecklistIntro": tr(loc, "audit_obs_checklist_intro"),
            "obsSelectAll": tr(loc, "audit_obs_select_all"),
            "obsSelectNone": tr(loc, "audit_obs_select_none"),
            "obsNotesAddAria": tr(loc, "audit_obs_notes_add_aria"),
            "obsNotesAddedCountTpl": tr(loc, "audit_obs_notes_added_count_tpl"),
            "obsNotesClearPicks": tr(loc, "audit_obs_notes_clear_picks"),
            "obsNotesBlockTitleLine": tr(loc, "audit_obs_notes_block_title"),
            "additionalNotesEmptyHint": tr(loc, "audit_additional_notes_empty_hint"),
            "additionalNotesRowMissingHint": tr(loc, "audit_additional_notes_row_missing"),
            "auditPieSectionAria": tr(loc, "audit_pie_section_aria"),
            "auditPieIaTitle": tr(loc, "audit_pie_ia_title"),
            "auditPieYearTitle": tr(loc, "audit_pie_year_title"),
            "auditPieRatingTitle": tr(loc, "audit_pie_rating_title"),
            "auditPieObsTitle": tr(loc, "audit_pie_obs_title"),
            "auditPieEmpty": tr(loc, "audit_pie_empty"),
            "auditPieUnavailable": tr(loc, "audit_pie_unavailable"),
            "auditPieRatingOther": tr(loc, "audit_pie_rating_other"),
            "obsDetailEmpty": tr(loc, "audit_obs_detail_empty"),
            "obsDetailOpenHint": tr(loc, "audit_obs_detail_open_hint"),
            "obsEmailSend": tr(loc, "audit_obs_email_send"),
            "obsEmailMissing": tr(loc, "audit_obs_email_missing"),
            "obsEmailSending": tr(loc, "audit_obs_email_sending"),
            "obsEmailOk": tr(loc, "audit_obs_email_ok"),
            "obsEmailFail": tr(loc, "audit_obs_email_fail"),
            "obsEmailSmtpNeeded": tr(loc, "audit_obs_email_smtp_needed"),
            "obsEmailMailtoHint": tr(loc, "audit_obs_email_mailto_hint"),
            "obsDetailDownloadPpt": tr(loc, "audit_obs_detail_download_ppt"),
            "obsDetailDownloadPptBusy": tr(loc, "audit_obs_detail_download_ppt_busy"),
            "obsDetailDownloadPptOk": tr(loc, "audit_obs_detail_download_ppt_ok"),
            "obsDetailDownloadPptFail": tr(loc, "audit_obs_detail_download_ppt_fail"),
            "obsDetailDownloadPptMissingLib": tr(loc, "audit_obs_detail_download_ppt_missing_lib"),
            "obsDetailSummaryLbl": tr(loc, "audit_obs_detail_summary"),
            "obsDetailRecLbl": tr(loc, "audit_obs_detail_recommendation"),
            "obsDetailImplDue": tr(loc, "audit_obs_detail_impl_due"),
            "obsDetailTargetDate": tr(loc, "audit_obs_detail_target_date"),
            "obsDetailRating": tr(loc, "audit_obs_detail_rating"),
            "obsDepartmentLabel": tr(loc, "audit_obs_department_label"),
            "obsRevisedDateLabel": tr(loc, "audit_obs_revised_date_label"),
            "obsAgingDaysLabel": tr(loc, "audit_obs_aging_days_label"),
            "obsAgingDaysSuffix": tr(loc, "audit_obs_aging_days_suffix"),
            "agingToggleLabel": tr(loc, "audit_aging_toggle_label"),
            "agingTitle": tr(loc, "audit_aging_title"),
            "agingColTimeFrame": tr(loc, "audit_aging_col_timeframe"),
            "agingTfNotDue": tr(loc, "audit_aging_tf_not_due"),
            "agingTfLt6Months": tr(loc, "audit_aging_tf_lt_6_months"),
            "agingTfLtYear": tr(loc, "audit_aging_tf_lt_year"),
            "agingTfOverYear": tr(loc, "audit_aging_tf_over_year"),
            "agingColTotal": tr(loc, "audit_aging_col_total"),
            "agingTitleAsOfTpl": tr(loc, "audit_aging_title_as_of_tpl"),
            "agingMatrixHint": tr(loc, "audit_aging_matrix_hint"),
            "agingRevisedToggleLabel": tr(loc, "audit_aging_revised_toggle_label"),
            "agingMatrixHintRevised": tr(loc, "audit_aging_matrix_hint_revised"),
            "planToggleLabel": tr(loc, "audit_plan_toggle_label"),
            "planTitle": tr(loc, "audit_plan_title"),
            "planColProjectName": tr(loc, "audit_plan_col_project_name"),
            "planColAuditableFunction": tr(loc, "audit_plan_col_auditable_function"),
            "planColResourceAllocated": tr(loc, "audit_plan_col_resource_allocated"),
            "planColProjectStatus": tr(loc, "audit_plan_col_project_status"),
            "planColPlanningPct": tr(loc, "audit_plan_col_planning_pct"),
            "planColFieldWorkPct": tr(loc, "audit_plan_col_fieldwork_pct"),
            "planColReportingPct": tr(loc, "audit_plan_col_reporting_pct"),
            "planDownloadPpt": tr(loc, "audit_plan_download_ppt"),
            "planUploadFile": tr(loc, "audit_plan_upload_file"),
            "planAddRow": tr(loc, "audit_plan_add_row"),
            "planColColorsLabel": tr(loc, "audit_plan_col_colors_label"),
            "planColColorsReset": tr(loc, "audit_plan_col_colors_reset"),
            "planCellColorsHint": tr(loc, "audit_plan_cell_colors_hint"),
            "planCellFillLabel": tr(loc, "audit_plan_cell_fill_label"),
            "planClearAllDataLabel": tr(loc, "audit_plan_clear_all_data"),
            "planClearAllDataAria": tr(loc, "audit_plan_clear_all_data_aria"),
            "planUploadNeedXlsx": tr(loc, "audit_plan_upload_need_xlsx"),
            "planUploadNeedJszip": tr(loc, "audit_plan_upload_need_jszip"),
            "planUploadBadType": tr(loc, "audit_plan_upload_bad_type"),
            "planUploadNoRows": tr(loc, "audit_plan_upload_no_rows"),
            "planUploadPptxFail": tr(loc, "audit_plan_upload_pptx_fail"),
            "companyLabel": tr(loc, "audit_company_label"),
            "subcompanyLabel": tr(loc, "audit_subcompany_label"),
            "brandCompaniesInFilterTitle": tr(loc, "audit_brand_companies_in_filter"),
            "brandSubcompaniesInFilterTitle": tr(loc, "audit_brand_subcompanies_in_filter"),
            "brandAllSubcompaniesHint": tr(loc, "audit_brand_all_subcompanies_active"),
            "brandAllCompanies": tr(loc, "audit_brand_all_companies"),
            "brandNoCompanySelected": tr(loc, "audit_brand_no_company_selected"),
            "brandChangeCompanies": tr(loc, "audit_brand_change_companies"),
            "reviewsToggleLabel": tr(loc, "audit_reviews_toggle_label"),
            "reviewsTitle": tr(loc, "audit_reviews_title"),
            "reviewsDownload": tr(loc, "audit_reviews_download"),
            "reviewsPlaceholder": tr(loc, "audit_reviews_placeholder"),
            "additionalNotesToggleLabel": tr(loc, "audit_additional_notes_toggle_label"),
            "deckAttachToggleLabel": tr(loc, "audit_deck_attach_toggle_label"),
            "deckUploadTitle": tr(loc, "audit_deck_upload_title"),
            "deckUploadHint": tr(loc, "audit_deck_upload_hint"),
            "deckBrowse": tr(loc, "audit_deck_browse"),
            "deckViewerTitle": tr(loc, "audit_deck_viewer_title"),
            "deckEmptyHint": tr(loc, "audit_deck_empty_hint"),
            "deckNoAttachment": tr(loc, "audit_deck_no_attachment"),
            "deckNoAttachmentTitle": tr(loc, "audit_deck_no_attachment_title"),
            "deckNoAttachmentOk": tr(loc, "audit_deck_no_attachment_ok"),
            "deckSlideHeading": tr(loc, "audit_deck_slide_heading"),
            "deckPptLegacyWarn": tr(loc, "audit_deck_ppt_legacy_warn"),
            "deckReadError": tr(loc, "audit_deck_read_error"),
            "deckDownloadCopy": tr(loc, "audit_deck_download_copy"),
            "deckIframeTitle": tr(loc, "audit_deck_iframe_title"),
            "deckPptxNote": tr(loc, "audit_deck_pptx_note"),
            "deckPptxFallbackNote": tr(loc, "audit_deck_pptx_fallback_note"),
            "deckSlidePrev": tr(loc, "audit_deck_slide_prev"),
            "deckSlideNext": tr(loc, "audit_deck_slide_next"),
            "deckSlideStatus": tr(loc, "audit_deck_slide_status"),
            "deckZoomOut": tr(loc, "audit_deck_zoom_out"),
            "deckZoomIn": tr(loc, "audit_deck_zoom_in"),
            "deckZoomReset": tr(loc, "audit_deck_zoom_reset"),
            "deckZoomLabel": tr(loc, "audit_deck_zoom_label"),
            "deckEngineSvg": tr(loc, "audit_deck_engine_svg"),
            "deckEngineCanvas": tr(loc, "audit_deck_engine_canvas"),
            "deckEngineLegacy": tr(loc, "audit_deck_engine_legacy"),
            "deckFullPage": tr(loc, "audit_deck_full_page"),
            "deckFullPageAria": tr(loc, "audit_deck_full_page_aria"),
            "deckBackDashboard": tr(loc, "audit_deck_back_dashboard"),
            "deckBackDashboardAria": tr(loc, "audit_deck_back_dashboard_aria"),
            **(
                {
                    "highRiskToggleLabel": tr("en", "audit_high_risk_toggle_label"),
                    "highRiskUploadTitle": tr("en", "audit_high_risk_upload_title"),
                    "highRiskUploadHint": tr("en", "audit_high_risk_upload_hint"),
                    "tgaViolationsToggleLabel": tr("en", "audit_tga_violations_toggle_label"),
                    "tgaViolationsUploadTitle": tr("en", "audit_tga_violations_upload_title"),
                    "tgaViolationsUploadHint": tr("en", "audit_tga_violations_upload_hint"),
                    "missingVehicleToggleLabel": tr("en", "audit_missing_vehicle_toggle_label"),
                    "missingVehicleUploadTitle": tr("en", "audit_missing_vehicle_upload_title"),
                    "missingVehicleUploadHint": tr("en", "audit_missing_vehicle_upload_hint"),
                    "internalAuditQuarterlyToggleLabel": tr("en", "audit_internal_audit_quarterly_toggle_label"),
                    "internalAuditQuarterlyUploadTitle": tr("en", "audit_internal_audit_quarterly_upload_title"),
                    "internalAuditQuarterlyUploadHint": tr("en", "audit_internal_audit_quarterly_upload_hint"),
                    "specialAssignmentToggleLabel": tr("en", "audit_special_assignment_toggle_label"),
                    "specialAssignmentUploadTitle": tr("en", "audit_special_assignment_upload_title"),
                    "specialAssignmentUploadHint": tr("en", "audit_special_assignment_upload_hint"),
                }
                if loc == "en"
                else {}
            ),
        },
    }


def build_file_filters_payload(
    df: pd.DataFrame,
    *,
    locale: str,
    primary_metric: str | None,
    primary_segment: str | None,
    trend_col: str | None,
    max_embed_rows: int = 4500,
    max_filter_dims: int = 10,
    max_options_per_dim: int = 150,
) -> dict[str, Any]:
    """Per-file filter dimensions + row slice so segment/trend charts can refilter in the browser."""
    loc = normalize_locale(locale)
    if not primary_metric or str(primary_metric) not in df.columns:
        return {"available": False}

    filter_keys: list[str] = []
    for c in df.columns:
        cs = str(c)
        if _is_internal_dashboard_col(cs):
            continue
        nu = int(df[c].nunique(dropna=True))
        if nu < 2 or nu > 120:
            continue
        if pd.api.types.is_numeric_dtype(df[c]) and nu > 72:
            continue
        filter_keys.append(cs)

    filter_keys = filter_keys[:max_filter_dims]
    if not filter_keys:
        return {"available": False}

    all_token = "__ALL__"
    options: dict[str, list[str]] = {}
    for c in filter_keys:
        raw = df[c].dropna()
        vals = sorted(
            {_filter_option_token(x) for x in raw.unique() if _filter_option_token(x) != ""},
            key=lambda x: (len(x), x),
        )[: max_options_per_dim - 1]
        options[c] = [all_token] + vals

    n_file = len(df)
    clip = df.iloc[:max_embed_rows] if len(df) > max_embed_rows else df
    cols_needed: list[str] = []
    for x in (
        [primary_metric, primary_segment, trend_col] + filter_keys
    ):
        if x and str(x) in df.columns and str(x) not in cols_needed:
            cols_needed.append(str(x))

    rows_out: list[dict[str, Any]] = []
    for _, r in clip.iterrows():
        rec: dict[str, Any] = {}
        for c in cols_needed:
            rec[c] = _json_safe_cell(r[c])
        rows_out.append(rec)

    mo: list[str] | None = None
    if trend_col and str(trend_col) in df.columns:
        ord_list = infer_month_order(df[trend_col])
        if ord_list:
            mo = [str(x).strip() for x in ord_list]

    sum_key = f"sum_{primary_metric}"
    return {
        "available": True,
        "filter_columns": [{"key": k, "label": k} for k in filter_keys],
        "options": options,
        "rows": rows_out,
        "segmentCol": primary_segment,
        "periodCol": trend_col,
        "metricCol": primary_metric,
        "sumKey": sum_key,
        "all_token": all_token,
        "month_order": mo,
        "total_rows_in_file": n_file,
        "embedded_row_cap": max_embed_rows,
        "truncated": n_file > max_embed_rows,
        "ui": {
            "hint": tr(loc, "ff_hint"),
            "all": tr(loc, "ff_all"),
            "matchTpl": tr(loc, "ff_match"),
            "loadedTpl": tr(loc, "ff_loaded"),
        },
    }


def anomaly_count(series: pd.Series) -> int:
    x = pd.to_numeric(series, errors="coerce").dropna()
    if x.shape[0] < 6:
        return 0
    q1 = x.quantile(0.25)
    q3 = x.quantile(0.75)
    iqr = q3 - q1
    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr
    return int(((x < low) | (x > high)).sum())


def finance_anomaly_rules(df: pd.DataFrame, detected: dict[str, str | None]) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    period_col = detected["period"]
    segment_col = detected["segment"]
    revenue_col = detected["revenue"] or detected["sales"]
    profit_col = detected["profit"]
    cost_col = detected["cost"]

    if revenue_col:
        s = pd.to_numeric(df[revenue_col], errors="coerce")
        neg = int((s < 0).sum())
        if neg > 0:
            alerts.append(
                {
                    "severity": "high",
                    "rule_key": "anomaly_neg_rev",
                    "rule": "Negative revenue values",
                    "count": neg,
                }
            )
        outliers = anomaly_count(df[revenue_col])
        if outliers > 0:
            alerts.append(
                {
                    "severity": "medium",
                    "rule_key": "anomaly_rev_outliers",
                    "rule": "Revenue outliers (IQR)",
                    "count": outliers,
                }
            )

    if profit_col and revenue_col:
        p = pd.to_numeric(df[profit_col], errors="coerce")
        r = pd.to_numeric(df[revenue_col], errors="coerce")
        margin = p / r.replace(0, pd.NA)
        bad_margin = int(((margin < -0.2) | (margin > 0.8)).fillna(False).sum())
        if bad_margin > 0:
            alerts.append(
                {
                    "severity": "high",
                    "rule_key": "anomaly_bad_margin",
                    "rule": "Unusual profit margin ratio",
                    "count": bad_margin,
                }
            )

    if cost_col and revenue_col:
        c = pd.to_numeric(df[cost_col], errors="coerce")
        r = pd.to_numeric(df[revenue_col], errors="coerce")
        high_cost = int((c > r).sum())
        if high_cost > 0:
            alerts.append(
                {
                    "severity": "medium",
                    "rule_key": "anomaly_cost_gt_rev",
                    "rule": "Cost exceeds revenue",
                    "count": high_cost,
                }
            )

    if period_col and segment_col and revenue_col:
        temp = (
            df[[period_col, segment_col, revenue_col]]
            .assign(_rev=pd.to_numeric(df[revenue_col], errors="coerce"))
            .dropna(subset=[period_col, segment_col])
        )
        # Duplicate keys may indicate data quality issue for finance reporting grain.
        dup_key = int(temp.duplicated(subset=[period_col, segment_col], keep=False).sum())
        if dup_key > 0:
            alerts.append(
                {
                    "severity": "medium",
                    "rule_key": "anomaly_dup_keys",
                    "rule": "Duplicate period+segment records",
                    "count": dup_key,
                }
            )

    return alerts


def build_finance_kpis(
    df: pd.DataFrame, detected: dict[str, str | None], locale: str = "en"
) -> list[dict[str, str]]:
    loc = normalize_locale(locale)
    revenue_col = detected["revenue"] or detected["sales"]
    sales_col = detected["sales"] or revenue_col
    profit_col = detected["profit"]
    cost_col = detected["cost"]
    kpis: list[dict[str, str]] = []

    if revenue_col:
        revenue = pd.to_numeric(df[revenue_col], errors="coerce")
        kpis.append(
            {
                "name": tr(loc, "kpi_total_revenue"),
                "value": f"{float(revenue.sum(skipna=True)):,.2f}",
            }
        )
    if sales_col:
        sales = pd.to_numeric(df[sales_col], errors="coerce")
        kpis.append(
            {
                "name": tr(loc, "kpi_total_sales"),
                "value": f"{float(sales.sum(skipna=True)):,.2f}",
            }
        )
    if profit_col:
        profit = pd.to_numeric(df[profit_col], errors="coerce")
        kpis.append(
            {
                "name": tr(loc, "kpi_total_profit"),
                "value": f"{float(profit.sum(skipna=True)):,.2f}",
            }
        )
    if revenue_col and profit_col:
        revenue = pd.to_numeric(df[revenue_col], errors="coerce")
        profit = pd.to_numeric(df[profit_col], errors="coerce")
        if float(revenue.sum(skipna=True)) != 0.0:
            margin = float(profit.sum(skipna=True) / revenue.sum(skipna=True) * 100)
            kpis.append(
                {"name": tr(loc, "kpi_gross_margin"), "value": f"{margin:.2f}%"}
            )
    if cost_col and revenue_col:
        cost = pd.to_numeric(df[cost_col], errors="coerce")
        revenue = pd.to_numeric(df[revenue_col], errors="coerce")
        if float(revenue.sum(skipna=True)) != 0.0:
            c2r = float(cost.sum(skipna=True) / revenue.sum(skipna=True) * 100)
            kpis.append(
                {"name": tr(loc, "kpi_cost_ratio"), "value": f"{c2r:.2f}%"}
            )
    return kpis


def to_html_table(
    df: pd.DataFrame,
    max_rows: int | None = 20,
    *,
    empty_message: str = "No data",
) -> str:
    if df.empty:
        return f"<p class='muted'>{html.escape(empty_message)}</p>"
    clip = df if max_rows is None else df.head(max_rows)
    th = "".join(f"<th>{html.escape(str(c))}</th>" for c in clip.columns)
    rows = []
    for _, r in clip.iterrows():
        tds = "".join(f"<td>{html.escape('' if pd.isna(v) else str(v))}</td>" for v in r.tolist())
        rows.append(f"<tr>{tds}</tr>")
    return f"<div class='table-wrap'><table><thead><tr>{th}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


_MAX_EMBEDDED_DECK_BYTES = 48 * 1024 * 1024


def build_embedded_slide_deck_payload(path: str | None, *, locale: str) -> dict[str, Any] | None:
    """Return a JSON-serializable blob for embedding a deck in the HTML report (base64)."""
    if not path or not str(path).strip():
        return None
    loc = normalize_locale(locale)
    p = Path(str(path).strip().strip('"')).expanduser()
    if not p.is_file():
        raise FileNotFoundError(str(p))
    if p.stat().st_size > _MAX_EMBEDDED_DECK_BYTES:
        raise ValueError(
            tr(loc, "err_deck_too_large", mb=_MAX_EMBEDDED_DECK_BYTES // (1024 * 1024))
        )
    ext = p.suffix.lower()
    if ext not in (".pptx", ".ppt", ".pdf"):
        raise ValueError(tr(loc, "err_deck_format"))
    mime = (
        "application/pdf"
        if ext == ".pdf"
        else (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            if ext == ".pptx"
            else "application/vnd.ms-powerpoint"
        )
    )
    b64 = base64.standard_b64encode(p.read_bytes()).decode("ascii")
    return {"file_name": p.name, "mime": mime, "data_base64": b64}


AUDIT_BUNDLE_MAX_FILES = 4


def resolve_attached_deck_for_workbook_index(
    deck_paths: list[str] | None,
    workbook_index: int,
    workbook_count: int,
) -> str | None:
    """One deck for all workbooks, or one deck per workbook (same order)."""
    paths = [str(p).strip() for p in (deck_paths or []) if str(p).strip()]
    if not paths:
        return None
    if len(paths) == 1:
        return paths[0]
    if len(paths) == workbook_count and 0 <= workbook_index < len(paths):
        return paths[workbook_index]
    return None


def build_embedded_slide_deck_bundle(
    *,
    fallback_path: str | None,
    by_company_paths: dict[str, str] | None,
    locale: str,
) -> dict[str, Any] | None:
    """Single deck, or per-company decks (+ optional fallback) for multi-workbook uploads."""
    loc = normalize_locale(locale)
    by_in = {
        str(k).strip(): v
        for k, v in (by_company_paths or {}).items()
        if v and str(v).strip() and str(k).strip()
    }
    by_company: dict[str, Any] = {}
    for token, path in by_in.items():
        p = build_embedded_slide_deck_payload(path, locale=loc)
        if p:
            by_company[token] = p
    fb = (
        build_embedded_slide_deck_payload(fallback_path, locale=loc)
        if fallback_path
        else None
    )
    if by_company:
        out: dict[str, Any] = {"by_company": by_company}
        if fb:
            out["fallback"] = fb
        return out
    return fb


def workbook_dashboard_tab_title(df: pd.DataFrame, fallback_stem: str) -> str:
    """Label for multi-shell dropdown: company name only if one distinct company, else file stem."""
    stem = (fallback_stem or "report").strip() or "report"
    try:
        df0 = df.dropna(how="all").dropna(axis=1, how="all")
    except Exception:
        return stem
    if df0.empty:
        return stem
    cm = resolve_audit_observation_columns(df0)
    if not cm or "company" not in cm:
        return stem
    col = cm["company"]
    toks = sorted(
        {
            _filter_option_token(x)
            for x in df0[col].dropna().unique()
            if _filter_option_token(x) != ""
        }
    )
    if len(toks) == 1:
        return toks[0]
    return stem


def build_multi_dashboard_shell(
    pages: list[tuple[str, str]],
    *,
    locale: str = "en",
    mail_api_script: str | None = None,
) -> str:
    """Single HTML page with a company/workbook dropdown; each option loads one full dashboard in an iframe."""
    if not pages:
        raise ValueError("No dashboard pages")
    loc = normalize_locale(locale)
    dir_ = "rtl" if loc == "ar" else "ltr"
    lang = "ar" if loc == "ar" else "en"
    titles = [p[0] for p in pages]
    blobs = [
        base64.standard_b64encode(p[1].encode("utf-8")).decode("ascii")
        for p in pages
    ]
    titles_js = json.dumps(titles, ensure_ascii=False)
    blobs_js = json.dumps(blobs, ensure_ascii=False)
    shell_title = html.escape(tr(loc, "multi_shell_title"))
    shell_hint = html.escape(tr(loc, "multi_shell_hint"))
    co_label = html.escape(tr(loc, "audit_company_label"))
    sel_aria = html.escape(tr(loc, "multi_shell_select"))
    font_link = html.escape(tr(loc, "font_link"))
    mail_head = (
        f"\n  <script>{mail_api_script}</script>"
        if (mail_api_script and mail_api_script.strip())
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="{lang}" dir="{dir_}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
{ROBOTS_META_HTML}  <title>{shell_title}</title>{mail_head}
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link href="{font_link}" rel="stylesheet" />
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ height: 100%; overflow-x: hidden; }}
    body {{ margin: 0; font-family: "Noto Sans Arabic", "Segoe UI", system-ui, sans-serif;
      background: #f0f2f5; color: #1a1a2e; min-height: 100vh; display: flex; flex-direction: column; overflow-y: auto; }}
    .bar {{
      background: #fff;
      border-bottom: 1px solid #dde1ea;
      padding: 14px 16px;
      flex-shrink: 0;
      box-shadow: 0 2px 8px rgba(0,0,0,.06);
    }}
    html.deck-open, body.deck-open {{ overflow: hidden !important; }}
    body.deck-open .bar {{ display: none; }}
    body.deck-open .frame-wrap {{
      position: fixed;
      inset: 0;
      min-height: 100vh;
      z-index: 9999;
      background: #111827;
      overflow: hidden;
    }}
    body.deck-open iframe {{
      min-height: 100vh;
      height: 100vh !important;
    }}
    .picker-row {{ display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }}
    .picker-lbl {{ font-weight: 700; font-size: 15px; color: #007a38; white-space: nowrap; }}
    .company-select {{
      flex: 1; min-width: 200px; max-width: 560px; padding: 11px 14px; font-size: 15px;
      border: 1px solid #ccd3df; border-radius: 10px; background: #fff; color: #0f172a;
      font-family: inherit;
    }}
    .company-select:focus {{ outline: 2px solid #00B050; outline-offset: 1px; border-color: #007a38; }}
    .shell-hint {{ margin: 10px 0 0; font-size: 12px; color: #64748b; line-height: 1.4; max-width: 720px; }}
    .frame-wrap {{ display: block; min-height: 70vh; overflow: visible; }}
    iframe {{ width: 100%; min-height: 70vh; border: 0; background: #fff; display: block; overflow: hidden; }}
  </style>
</head>
<body>
  <div class="bar">
    <div class="picker-row">
      <label for="multi-co-sel" class="picker-lbl">{co_label}</label>
      <select id="multi-co-sel" class="company-select" aria-label="{sel_aria}"></select>
    </div>
    <p class="shell-hint">{shell_hint}</p>
  </div>
  <div class="frame-wrap">
    <iframe id="dash-frame" title="Dashboard" referrerpolicy="no-referrer" allow="fullscreen" scrolling="no"></iframe>
  </div>
  <script>
(function() {{
  var titles = {titles_js};
  var blobs = {blobs_js};
  var sel = document.getElementById('multi-co-sel');
  var iframe = document.getElementById('dash-frame');
  var lastBlobUrl = null;
  var frameResizeObserver = null;
  var frameSyncTimer = null;
  var FALLBACK_FRAME_HEIGHT_PX = 1200;
  function isDeckModalOpen(doc) {{
    if (!doc) return false;
    try {{
      var ids = [
        'audit-deck-modal',
        'audit-aging-panel',
        'audit-plan-panel',
        'audit-reviews-panel',
        'audit-obs-detail-panel'
      ];
      for (var i = 0; i < ids.length; i++) {{
        var modal = doc.getElementById(ids[i]);
        if (!modal) continue;
        if (modal.getAttribute('aria-hidden') === 'true') continue;
        var st = modal.style && modal.style.display ? String(modal.style.display).toLowerCase() : '';
        if (st === 'none') continue;
        return true;
      }}
      return false;
    }} catch (e) {{
      return false;
    }}
  }}
  function syncFrameHeight() {{
    if (!iframe) return;
    try {{
      var doc = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
      if (!doc) {{
        try {{ document.body.classList.remove('deck-open'); }} catch (_dc0) {{}}
        iframe.style.height = String(FALLBACK_FRAME_HEIGHT_PX) + 'px';
        return;
      }}
      var deckOpen = isDeckModalOpen(doc);
      try {{ document.body.classList.toggle('deck-open', !!deckOpen); }} catch (_dc1) {{}}
      if (deckOpen) {{
        var vh = (window && window.innerHeight) ? window.innerHeight : 900;
        iframe.style.height = String(Math.max(700, vh)) + 'px';
        return;
      }}
      var de = doc.documentElement;
      var body = doc.body;
      var h1 = de ? de.scrollHeight : 0;
      var h2 = body ? body.scrollHeight : 0;
      var h3 = de ? de.offsetHeight : 0;
      var h4 = body ? body.offsetHeight : 0;
      var h5 = de ? de.clientHeight : 0;
      var h6 = body ? body.clientHeight : 0;
      var h = Math.max(h1, h2, h3, h4, h5, h6, 700);
      iframe.style.height = String(h) + 'px';
    }} catch (e) {{
      try {{ document.body.classList.remove('deck-open'); }} catch (_dc2) {{}}
      iframe.style.height = String(FALLBACK_FRAME_HEIGHT_PX) + 'px';
    }}
  }}
  function setDeckOpenState(open) {{
    try {{ document.body.classList.toggle('deck-open', !!open); }} catch (_do0) {{}}
    try {{ document.documentElement.classList.toggle('deck-open', !!open); }} catch (_do1) {{}}
    try {{
      document.documentElement.style.overflow = open ? 'hidden' : '';
      document.body.style.overflow = open ? 'hidden' : '';
    }} catch (_do2) {{}}
    if (!!open) {{
      var vh = (window && window.innerHeight) ? window.innerHeight : 900;
      iframe.style.height = String(Math.max(700, vh)) + 'px';
    }} else {{
      syncFrameHeight();
    }}
  }}
  function deckActionFromKeyEvent(ev) {{
    if (!ev) return "";
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return "";
    var k = String(ev.key || "");
    if (k === "Escape") return "exit";
    if (k === "F11") return "toggle_fullpage";
    if (k === "Home") return "first";
    if (k === "End") return "last";
    if (k === "ArrowLeft" || k === "ArrowUp" || k === "PageUp") return "prev";
    if (k === "ArrowRight" || k === "ArrowDown" || k === "PageDown" || k === " " || k === "Enter") return "next";
    return "";
  }}
  function bindFrameAutoHeight() {{
    if (!iframe) return;
    try {{ if (frameResizeObserver) frameResizeObserver.disconnect(); }} catch (e) {{}}
    frameResizeObserver = null;
    try {{ if (frameSyncTimer) clearInterval(frameSyncTimer); }} catch (_ti) {{}}
    frameSyncTimer = null;
    syncFrameHeight();
    try {{
      var doc = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
      if (!doc) return;
      if (window.ResizeObserver) {{
        frameResizeObserver = new ResizeObserver(function () {{ syncFrameHeight(); }});
        if (doc.documentElement) frameResizeObserver.observe(doc.documentElement);
        if (doc.body) frameResizeObserver.observe(doc.body);
      }}
      frameSyncTimer = setInterval(syncFrameHeight, 800);
    }} catch (e) {{}}
  }}
  function utf8FromB64(b64) {{
    var bin = atob(b64);
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new TextDecoder('utf-8').decode(bytes);
  }}
  function show(ix) {{
    if (ix < 0 || ix >= blobs.length) ix = 0;
    var html = utf8FromB64(blobs[ix]);
    iframe.removeAttribute('src');
    iframe.srcdoc = html;
    iframe.style.height = String(FALLBACK_FRAME_HEIGHT_PX) + 'px';
    if (sel) sel.value = String(ix);
  }}
  iframe.addEventListener('load', function () {{
    bindFrameAutoHeight();
    setTimeout(syncFrameHeight, 60);
    setTimeout(syncFrameHeight, 220);
    setTimeout(syncFrameHeight, 700);
  }});
  window.addEventListener('resize', function () {{ syncFrameHeight(); }});
  window.addEventListener('message', function (ev) {{
    var data = ev && ev.data ? ev.data : null;
    if (!data || data.type !== 'deck-modal-state') return;
    setDeckOpenState(!!data.open);
  }});
  window.addEventListener('keydown', function (ev) {{
    var t = ev && ev.target;
    if (t && t.closest && t.closest("input, textarea, select, [contenteditable=true]")) return;
    var action = deckActionFromKeyEvent(ev);
    if (!action) return;
    try {{
      var doc = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
      if (!isDeckModalOpen(doc)) return;
    }} catch (_k0) {{
      return;
    }}
    try {{ ev.preventDefault(); }} catch (_k1) {{}}
    try {{
      if (iframe && iframe.contentWindow) {{
        iframe.contentWindow.postMessage({{ type: "deck-key-command", action: action }}, "*");
      }}
    }} catch (_k2) {{}}
  }}, true);
  window.addEventListener('beforeunload', function () {{
    if (frameResizeObserver) try {{ frameResizeObserver.disconnect(); }} catch (e) {{}}
    if (frameSyncTimer) try {{ clearInterval(frameSyncTimer); }} catch (e) {{}}
    if (lastBlobUrl) try {{ URL.revokeObjectURL(lastBlobUrl); }} catch (e) {{}}
  }});
  for (var i = 0; i < titles.length; i++) {{
    var opt = document.createElement('option');
    opt.value = String(i);
    opt.textContent = titles[i];
    sel.appendChild(opt);
  }}
  sel.addEventListener('change', function () {{
    show(parseInt(sel.value, 10) || 0);
  }});
  show(0);
}})();
  </script>
</body>
</html>"""


def build_deck_attach_toggle_html(
    locale: str,
    enabled_attachment_kinds: set[str] | frozenset[str] | None = None,
) -> str:
    """Render attachment toggle checkboxes; omit kinds disabled for the tenant company."""
    loc = normalize_locale(locale)
    enabled = (
        ALL_ATTACHMENT_KINDS
        if enabled_attachment_kinds is None
        else frozenset(enabled_attachment_kinds)
    )
    parts: list[str] = []
    for kind, cb_id, lbl_id in _ATTACHMENT_TOGGLE_SPECS:
        if kind not in enabled:
            continue
        if loc != "en" and kind != "deck":
            continue
        parts.append(
            '<label class="audit-obs-aging-toggle">'
            f'<input type="checkbox" id="{cb_id}" aria-controls="audit-deck-modal" aria-haspopup="dialog" />'
            f'<span id="{lbl_id}"></span>'
            "</label>"
        )
    return "".join(parts)


def generate_finance_report(
    df: pd.DataFrame,
    source_name: str,
    sheet_name: str | None = None,
    locale: str = "en",
    attached_deck_path: str | None = None,
    *,
    embedded_decks_by_company_path: dict[str, str] | None = None,
    attached_high_risk_deck_path: str | None = None,
    embedded_high_risk_decks_by_company_path: dict[str, str] | None = None,
    attached_tga_violations_deck_path: str | None = None,
    embedded_tga_violations_decks_by_company_path: dict[str, str] | None = None,
    attached_missing_vehicle_deck_path: str | None = None,
    embedded_missing_vehicle_decks_by_company_path: dict[str, str] | None = None,
    attached_internal_audit_quarterly_deck_path: str | None = None,
    embedded_internal_audit_quarterly_decks_by_company_path: dict[str, str] | None = None,
    attached_special_assignment_deck_path: str | None = None,
    embedded_special_assignment_decks_by_company_path: dict[str, str] | None = None,
    allow_multiple_audit_companies: bool = False,
    enabled_attachment_kinds: set[str] | frozenset[str] | None = None,
    company_entity=None,
) -> tuple[str, dict[str, Any]]:
    loc = normalize_locale(locale)
    enabled_kinds = (
        ALL_ATTACHMENT_KINDS
        if enabled_attachment_kinds is None
        else frozenset(enabled_attachment_kinds)
    )
    read_note_codes: list[str] = list(
        getattr(df, "attrs", {}).get(ATTR_READ_NOTES, [])
    ) if hasattr(df, "attrs") else []

    df_base = df.dropna(how="all").dropna(axis=1, how="all")
    if df_base.empty:
        raise ValueError(tr(loc, "err_empty_df"))

    profile = build_detected_profile(df_base)
    df_work, profile = apply_dashboard_column_fallbacks(df_base, profile, locale=loc)
    det = detected_for_engine(profile)

    extra_warnings: list[str] = []
    for code in read_note_codes:
        if code == "read_unnamed_renamed":
            extra_warnings.append(tr(loc, "read_note_unnamed"))
        elif code == "read_ai_labels":
            extra_warnings.append(tr(loc, "read_note_ai_labels"))
        elif code.startswith("read_header_row:"):
            row = code.split(":", 1)[-1]
            extra_warnings.append(tr(loc, "read_note_header_row", row=row))
    if profile.get("_meta_inferred_period") and not profile.get("_meta_row_order_period"):
        extra_warnings.append(
            tr(loc, "warn_period_inferred", col=str(profile["period"]))
        )
    if profile.get("_meta_row_order_period"):
        extra_warnings.append(tr(loc, "warn_period_row_order"))
    if profile.get("_meta_inferred_segment"):
        extra_warnings.append(
            tr(loc, "warn_segment_inferred", col=str(profile["segment"]))
        )
    if profile.get("_meta_synthetic_segment"):
        extra_warnings.append(tr(loc, "warn_segment_synthetic"))

    schema_errors, schema_warnings = validate_schema_finance(
        df_work, locale=loc, detected=det
    )
    schema_warnings = list(schema_warnings) + extra_warnings
    if schema_errors:
        raise ValueError(tr(loc, "err_schema_prefix") + " | ".join(schema_errors))

    n_rows, n_cols = df_work.shape
    num_cols = numeric_columns(df_work)
    cat_cols = [c for c in categorical_columns(df_work) if c not in num_cols]
    miss = int(df_work.isna().sum().sum())
    dup = int(df_work.duplicated().sum())
    content_fp = content_fingerprint(df_work, source_name)
    theme = theme_from_fingerprint(content_fp)
    layout_spin = int(content_fp[48:50], 16) % 6

    # Primary metric (best available numeric)
    primary_metric = det["revenue"] or det["sales"] or det["profit"]
    if not primary_metric and num_cols:
        primary_metric = num_cols[0]

    primary_segment = det["segment"]
    trend_col = det["period"]

    segment_table = pd.DataFrame()
    if primary_metric:
        s = pd.to_numeric(df_work[primary_metric], errors="coerce")
        if primary_segment:
            tmp = (
                df_work.assign(_m=s)
                .groupby(primary_segment, dropna=True)["_m"]
                .sum()
                .sort_values(ascending=False)
                .reset_index()
                .rename(columns={primary_segment: "segment", "_m": f"sum_{primary_metric}"})
            )
            if not tmp.empty:
                segment_table = tmp

    trend_table = pd.DataFrame()
    if primary_metric and trend_col:
        metric = pd.to_numeric(df_work[primary_metric], errors="coerce")
        month_order = infer_month_order(df_work[trend_col])
        trend = (
            df_work.assign(_m=metric, _t=df_work[trend_col].astype(str).str.strip())
            .groupby("_t", dropna=True)["_m"]
            .sum()
            .reset_index()
            .rename(columns={"_t": trend_col, "_m": f"sum_{primary_metric}"})
        )
        if month_order:
            order_map: dict[str, int] = {}
            for i, v in enumerate(month_order):
                vs = str(v).strip()
                order_map[vs] = i
                order_map[vs.lower()] = i
            trend["_ord"] = trend[trend_col].astype(str).str.strip().map(
                lambda x, om=order_map: om.get(x, om.get(x.lower(), 9999))
            )
            trend = trend.sort_values("_ord").drop(columns=["_ord"])
        else:
            trend = trend.sort_values(f"sum_{primary_metric}", ascending=False)
        trend_table = trend

    corr_table = pd.DataFrame()
    if len(num_cols) >= 2:
        ndf = pd.DataFrame(
            {c: pd.to_numeric(df_work[c], errors="coerce") for c in num_cols}
        )
        corr = ndf.corr(numeric_only=True)
        pairs = []
        cols = list(corr.columns)
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                v = corr.iloc[i, j]
                if pd.notna(v):
                    pairs.append((cols[i], cols[j], float(v)))
        pairs.sort(key=lambda x: abs(x[2]), reverse=True)
        if pairs:
            corr_table = pd.DataFrame(pairs[:8], columns=["metric_a", "metric_b", "correlation"])

    anomaly_alerts = finance_anomaly_rules(df_work, det)
    finance_kpis = build_finance_kpis(df_work, det, locale=loc)
    finance_trends = build_finance_trends_payload(df_work, det, locale=loc)
    file_filters = build_file_filters_payload(
        df_work,
        locale=loc,
        primary_metric=primary_metric,
        primary_segment=primary_segment,
        trend_col=trend_col,
    )

    audit_colmap = resolve_audit_observation_columns(df_work)
    audit_obs_payload: dict[str, Any] = {"available": False}
    if audit_colmap:
        if not allow_multiple_audit_companies:
            _raise_if_multiple_audit_companies(df_work, audit_colmap, locale=loc)
        audit_obs_payload = build_audit_observation_payload(
            df_work, audit_colmap, locale=loc
        )

    ui_font = '"Noto Sans Arabic", "Outfit", system-ui, sans-serif'
    chart_payload: dict[str, Any] = {
        "segment": segment_table.head(12).to_dict(orient="records") if not segment_table.empty else [],
        "trend": trend_table.head(24).to_dict(orient="records") if not trend_table.empty else [],
        "theme": theme,
        "fingerprint_short": content_fp[:14],
        "finance_trends": finance_trends,
        "file_filters": file_filters,
        "audit_observation": audit_obs_payload,
        "ui": {
            "fontFamily": ui_font,
            "revenue": tr(loc, "metric_revenue"),
            "expenses": tr(loc, "metric_expenses"),
            "profit": tr(loc, "metric_profit"),
            "allCategories": tr(loc, "ft_all_categories"),
            "monthly": tr(loc, "ft_monthly"),
            "quarterly": tr(loc, "ft_quarterly"),
            "annual": tr(loc, "ft_annual"),
            "stackTitle": tr(loc, "ft_stack_title"),
            "ftDefaultReason": tr(loc, "ft_unavailable_default"),
        },
    }
    chart_payload["embedded_slide_deck"] = (
        build_embedded_slide_deck_bundle(
            fallback_path=attached_deck_path,
            by_company_paths=embedded_decks_by_company_path,
            locale=loc,
        )
        if "deck" in enabled_kinds
        else None
    )
    if normalize_locale(locale) == "en":
        if "highRisk" in enabled_kinds:
            hr_embedded = build_embedded_slide_deck_bundle(
                fallback_path=attached_high_risk_deck_path,
                by_company_paths=embedded_high_risk_decks_by_company_path,
                locale=loc,
            )
            if hr_embedded:
                chart_payload["embedded_high_risk_slide_deck"] = hr_embedded
        if "tgaViolations" in enabled_kinds:
            tga_embedded = build_embedded_slide_deck_bundle(
                fallback_path=attached_tga_violations_deck_path,
                by_company_paths=embedded_tga_violations_decks_by_company_path,
                locale=loc,
            )
            if tga_embedded:
                chart_payload["embedded_tga_violations_slide_deck"] = tga_embedded
        if "missingVehicle" in enabled_kinds:
            mv_embedded = build_embedded_slide_deck_bundle(
                fallback_path=attached_missing_vehicle_deck_path,
                by_company_paths=embedded_missing_vehicle_decks_by_company_path,
                locale=loc,
            )
            if mv_embedded:
                chart_payload["embedded_missing_vehicle_slide_deck"] = mv_embedded
        if "internalAuditQuarterly" in enabled_kinds:
            iaq_embedded = build_embedded_slide_deck_bundle(
                fallback_path=attached_internal_audit_quarterly_deck_path,
                by_company_paths=embedded_internal_audit_quarterly_decks_by_company_path,
                locale=loc,
            )
            if iaq_embedded:
                chart_payload["embedded_internal_audit_quarterly_slide_deck"] = iaq_embedded
        if "specialAssignment" in enabled_kinds:
            sa_embedded = build_embedded_slide_deck_bundle(
                fallback_path=attached_special_assignment_deck_path,
                by_company_paths=embedded_special_assignment_decks_by_company_path,
                locale=loc,
            )
            if sa_embedded:
                chart_payload["embedded_special_assignment_slide_deck"] = sa_embedded
    logo_catalog = build_company_logo_catalog(company_entity)
    chart_payload["brand_logo_catalog"] = logo_catalog

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stat_tiles = "".join(
        f'<div class="stat-tile st-{(i + layout_spin) % 6}"><span class="st-label">{html.escape(lab)}</span>'
        f'<span class="st-val">{val}</span></div>'
        for i, (lab, val) in enumerate(
            [
                (tr(loc, "stat_rows"), n_rows),
                (tr(loc, "stat_cols"), n_cols),
                (tr(loc, "stat_missing"), miss),
                (tr(loc, "stat_dup"), dup),
                (tr(loc, "stat_numeric"), len(num_cols)),
                (tr(loc, "stat_category"), len(cat_cols)),
            ]
        )
    )
    if anomaly_alerts:
        ad_rows: list[dict[str, Any]] = []
        for a in anomaly_alerts:
            rk = a.get("rule_key", "")
            rule_txt = tr(loc, rk) if rk else str(a.get("rule", ""))
            ad_rows.append(
                {
                    tr(loc, "col_severity"): tr(loc, "sev_" + str(a["severity"]).lower()),
                    tr(loc, "col_rule"): rule_txt,
                    tr(loc, "col_count"): a["count"],
                }
            )
        alert_table = pd.DataFrame(ad_rows)
    else:
        alert_table = pd.DataFrame(
            [
                {
                    tr(loc, "col_severity"): tr(loc, "sev_info"),
                    tr(loc, "col_rule"): tr(loc, "anomaly_none_row"),
                    tr(loc, "col_count"): 0,
                }
            ]
        )
    report_id = str(uuid.uuid4())
    _stem_raw = os.path.splitext(os.path.basename(source_name))[0]
    _safe_stem = re.sub(r"[^\w\-.]+", "_", _stem_raw, flags=re.UNICODE).strip("._") or "report"
    _safe_stem = _safe_stem[:96]
    download_html_filename = f"report-{_safe_stem}.html"
    download_filename_json = json.dumps(download_html_filename, ensure_ascii=False)
    audit_payload: dict[str, Any] = {
        "report_id": report_id,
        "report_version": REPORT_VERSION,
        "generated_at": generated_at,
        "source_name": source_name,
        "sheet_name": sheet_name,
        "rows": n_rows,
        "columns": n_cols,
        "missing_cells": miss,
        "duplicate_rows": dup,
        "detected_columns": {
            k: v
            for k, v in profile.items()
            if not str(k).startswith("_")
        },
        "schema_warnings": schema_warnings,
        "triggered_anomalies": anomaly_alerts,
        "content_sha256": content_fp,
        "theme_hues": theme,
        "finance_kpis": finance_kpis,
        "audit_observation": audit_obs_payload,
        "locale": loc,
    }

    audit_obs_root_display = "none"
    audit_top_bar_display = "none"
    default_nav_display = "flex"
    default_stat_grid_display = ""
    audit_obs_type_box_display = "none"
    if audit_obs_payload.get("available"):
        audit_obs_root_display = "block"
        audit_top_bar_display = "block"
        default_nav_display = "none"
        default_stat_grid_display = "none"
        if audit_obs_payload.get("has_observation_type"):
            audit_obs_type_box_display = "flex"

    th1, th2, th3 = theme["h1"], theme["h2"], theme["h3"]
    html_lang = "ar" if loc == "ar" else "en"
    html_dir = "rtl" if loc == "ar" else "ltr"
    page_title = html.escape(tr(loc, "title_doc", file=str(source_name)))
    font_url = tr(loc, "font_link")
    logo_data_uri = logo_catalog.get("default") or detect_brand_logo_data_uri()
    logo_display = "flex"
    logo_button_display = "inline-flex" if logo_data_uri else "none"
    logo_src_attr = html.escape(logo_data_uri)
    deck_attach_toggle_html = build_deck_attach_toggle_html(loc, enabled_kinds)
    html_out = f"""<!DOCTYPE html>
<html lang="{html_lang}" dir="{html_dir}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
{ROBOTS_META_HTML}  <title>{page_title}</title>
  <meta name="excel-dashboard-ui" content="{REPORT_VERSION}" />
  <!-- plan-upload:v4-fetch-only (no FileReader for audit plan file reads) -->
  <script>{_MAIL_API_MARKER}</script>
  <script>{_PLAN_PARSE_API_MARKER}</script>
  <script>{_MAIL_API_FALLBACK_MARKER}</script>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="{html.escape(font_url)}" rel="stylesheet" />
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/pptxgenjs@3.12.0/dist/pptxgen.bundle.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js" onerror="var s=document.createElement('script');s.src='https://unpkg.com/jszip@3.10.1/dist/jszip.min.js';document.head.appendChild(s);"></script>
  <script src="https://cdn.jsdelivr.net/npm/pptxviewjs@1.1.9/dist/PptxViewJS.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js" onerror="var s=document.createElement('script');s.src='https://unpkg.com/xlsx@0.18.5/dist/xlsx.full.min.js';document.head.appendChild(s);"></script>
  <style>
    :root {{
      --bg-deep: #ffffff;
      --bg-card: #f1f5f9;
      --stroke: rgba(15, 23, 42, 0.12);
      --text: #0f172a;
      --muted: #64748b;
      --dyn-h1: {th1};
      --dyn-h2: {th2};
      --dyn-h3: {th3};
      --accent: hsl(var(--dyn-h1), 76%, 42%);
      --accent2: hsl(var(--dyn-h2), 74%, 36%);
      --glow: hsla(var(--dyn-h1), 78%, 40%, 0.42);
      --total-box-bg: #0f172a;
      --total-box-border: rgba(255, 255, 255, 0.14);
      --total-box-text: #cbd5e1;
      --total-box-value: #f8fafc;
      --page-pad: clamp(0.65rem, 2.5vw, 1.35rem);
    }}
    * {{ box-sizing: border-box; }}
    html {{
      overflow-x: hidden;
      width: 100%;
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      width: 100%;
      overflow-x: hidden;
      overflow-y: auto;
      color: var(--text);
      font-family: "Noto Sans Arabic", "Outfit", system-ui, sans-serif;
      background: #ffffff;
      background-image: none;
    }}
    /* In multi-file shell, keep a single outer scrollbar only. */
    body.multi-shell-embedded {{
      overflow-y: hidden !important;
    }}
    .noise {{
      pointer-events: none;
      position: fixed;
      inset: 0;
      opacity: 0.02;
      background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
    }}
    .brand-strip {{
      width: 100%;
      display: {logo_display};
      align-items: center;
      justify-content: flex-start;
      padding: 0.55rem var(--page-pad) 0.35rem;
      box-sizing: border-box;
      position: relative;
      z-index: 2;
    }}
    body.audit-deck-open .brand-strip,
    body.audit-deck-open #brand-context-aside {{
      display: none !important;
    }}
    .brand-strip-inner {{
      display: flex;
      flex-direction: row;
      align-items: stretch;
      justify-content: flex-start;
      gap: 0.75rem;
      flex-wrap: wrap;
      width: 100%;
      max-width: 100%;
    }}
    .brand-logo-cluster {{
      display: flex;
      flex-direction: row;
      align-items: center;
      flex-shrink: 0;
      max-width: 100%;
      min-width: 0;
    }}
    #brand-company-filter-host {{
      display: none;
      flex-direction: row;
      flex-wrap: nowrap;
      align-items: flex-end;
      width: 100%;
      max-width: none;
      min-width: 0;
      margin: 0;
      padding: 0;
      box-sizing: border-box;
      align-self: stretch;
    }}
    #brand-company-filter-host.brand-company-filter-host--visible {{
      display: flex;
    }}
    #brand-company-filter-host.brand-company-filter-host--visible.brand-company-filter-host--hidden {{
      display: none !important;
    }}
    #brand-company-filter-host.brand-company-filter-host--sc-only {{
      flex-direction: column;
      align-items: stretch;
      flex-wrap: nowrap;
      gap: 0.35rem;
    }}
    #brand-company-filter-host.brand-company-filter-host--sc-only .audit-dim-filter-block {{
      flex: 1 1 auto;
      width: 100%;
      max-width: none;
      min-width: 0;
    }}
    .brand-context-head-row {{
      display: flex;
      flex-direction: row;
      align-items: flex-start;
      justify-content: space-between;
      gap: 0.45rem;
      width: 100%;
    }}
    .brand-context-head-row .brand-context-kicker {{
      flex: 1 1 auto;
      min-width: 0;
    }}
    .brand-company-filter-reopen {{
      flex-shrink: 0;
      margin: 0;
      padding: 0.1rem 0.38rem;
      font: inherit;
      font-size: 0.55rem;
      font-weight: 700;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      color: #475569;
      background: #ffffff;
      border: 1px solid rgba(15, 23, 42, 0.16);
      border-radius: 6px;
      cursor: pointer;
      white-space: nowrap;
    }}
    .brand-company-filter-reopen:hover {{
      border-color: rgba(15, 23, 42, 0.28);
      background: #f8fafc;
    }}
    .brand-company-filter-reopen:focus-visible {{
      outline: 2px solid rgba(15, 23, 42, 0.35);
      outline-offset: 2px;
    }}
    .brand-context-aside {{
      display: none;
      flex-direction: column;
      justify-content: flex-start;
      gap: 0.32rem;
      flex: 1 1 210px;
      min-width: min(100%, 13.5rem);
      max-width: min(26rem, 100%);
      padding: 0.32rem 0.5rem;
      border-radius: 10px;
      background: #ffffff;
      border: 1px solid rgba(15, 23, 42, 0.12);
      box-shadow: 0 4px 14px rgba(15, 23, 42, 0.08);
      box-sizing: border-box;
    }}
    body.multi-shell-embedded #brand-context-aside {{
      display: flex !important;
    }}
    body.multi-shell-embedded #brand-context-company-names {{
      display: none !important;
    }}
    body.multi-shell-embedded .brand-context-aside--sc-only #brand-context-company-names {{
      display: block !important;
    }}
    .brand-context-aside.brand-context-aside--visible {{
      display: flex;
    }}
    .brand-context-kicker {{
      font-size: 0.65rem;
      font-weight: 700;
      letter-spacing: 0.02em;
      text-transform: none;
      color: #64748b;
      line-height: 1.2;
    }}
    .brand-context-names {{
      font-size: 0.74rem;
      font-weight: 700;
      color: #0f172a;
      line-height: 1.4;
      word-break: break-word;
    }}
    .brand-context-names .brand-context-chip {{
      display: inline-block;
      margin: 0.08rem 0.15rem 0.08rem 0;
      padding: 0.14rem 0.45rem;
      border-radius: 999px;
      background: rgba(15, 23, 42, 0.06);
      border: 1px solid rgba(15, 23, 42, 0.12);
      font-size: 0.7rem;
      font-weight: 700;
      color: #0f172a;
    }}
    .brand-context-names .brand-context-chip--muted {{
      display: block;
      width: 100%;
      box-sizing: border-box;
      margin: 0.12rem 0 0;
      padding: 0.42rem 0.65rem;
      border-radius: 999px;
      background: rgba(15, 23, 42, 0.06);
      border: 1px solid rgba(15, 23, 42, 0.1);
      font-size: 0.72rem;
      font-weight: 700;
      color: #0f172a;
      line-height: 1.35;
      text-align: left;
    }}
    .brand-context-names .brand-context-all {{
      font-weight: 800;
      color: #0f172a;
    }}
    .brand-logo-wrap {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 0.28rem 0.4rem;
      border-radius: 12px;
      background: rgba(255, 255, 255, 0.92);
      border: 1px solid rgba(15, 23, 42, 0.12);
      box-shadow: 0 6px 20px rgba(0, 0, 0, 0.22);
      max-width: min(32rem, 100%);
    }}
    button.brand-logo-wrap.brand-logo-btn {{
      font: inherit;
      margin: 0;
      cursor: pointer;
      appearance: none;
      -webkit-appearance: none;
    }}
    button.brand-logo-wrap.brand-logo-btn:focus-visible {{
      outline: 2px solid hsl(var(--dyn-h1), 72%, 48%);
      outline-offset: 3px;
    }}
    button.brand-logo-wrap.brand-logo-btn:hover {{
      border-color: rgba(15, 23, 42, 0.22);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
    }}
    .brand-logo {{
      display: block;
      width: auto;
      max-width: 100%;
      max-height: 68px;
      object-fit: contain;
      image-rendering: auto;
    }}
    .nav {{
      position: relative;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.4rem;
      width: 100%;
      max-width: 100%;
      margin: 0;
      padding: 0.65rem var(--page-pad);
      box-sizing: border-box;
      background: rgba(255, 255, 255, 0.94);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--stroke);
    }}
    .audit-top-bar {{
      position: relative;
      z-index: 1;
      background: #f8fafc;
      backdrop-filter: none;
      border: 1px solid var(--stroke);
      border-radius: 20px;
      padding: 1rem 1.15rem 1.1rem;
      margin-bottom: 1rem;
    }}
    .audit-top-inner {{
      max-width: 100%;
      margin: 0;
      width: 100%;
    }}
    .audit-top-row-ia {{
      width: 100%;
    }}
    .audit-row-ia-plus-total {{
      margin-bottom: 0.5rem;
    }}
    .audit-ia-tiles-unified {{
      display: flex;
      flex-direction: row;
      flex-wrap: wrap;
      align-items: stretch;
      gap: 0;
      width: 100%;
      border-radius: 10px;
      overflow: hidden;
      border: 1px solid rgba(15, 23, 42, 0.1);
    }}
    #audit-ia-tiles.audit-ia-tiles-host {{
      display: contents;
    }}
    #audit-ia-tiles > .stat-tile,
    .audit-ia-tiles-unified > .audit-box-total {{
      flex: 1 1 0;
      min-width: 0;
      max-width: 100%;
    }}
    .audit-ia-tiles--nav {{
      margin-bottom: 0 !important;
    }}
    #audit-ia-tiles > .stat-tile {{
      padding: 0.75rem 0.6rem;
      border-radius: 0;
      min-height: 4.25rem;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
      border-right: 1px solid rgba(15, 23, 42, 0.12);
    }}
    .audit-ia-tiles-unified > .audit-box-total {{
      border-left: 1px solid rgba(15, 23, 42, 0.12);
    }}
    .audit-ia-tiles-unified > .audit-box-total .audit-total-compact {{
      border-radius: 0;
      border: none;
      min-height: 4.25rem;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 0.75rem 0.6rem;
    }}
    .audit-ia-tiles-unified > .audit-box-total .st-val {{
      order: 1;
      font-size: 1.55rem;
      margin-top: 0;
    }}
    .audit-ia-tiles-unified > .audit-box-total .st-label {{
      order: 2;
      font-size: 0.72rem;
      font-weight: 700;
      margin-top: 0.35rem;
    }}
    .audit-ia-tiles-unified > .audit-box-total .audit-total-sub {{
      order: 3;
      margin-top: 0.25rem;
      font-size: 0.68rem;
    }}
    #audit-ia-tiles > .stat-tile .st-label {{
      font-size: 0.72rem;
      letter-spacing: 0.04em;
      font-weight: 700;
      line-height: 1.25;
      order: 2;
      margin-top: 0.35rem;
    }}
    #audit-ia-tiles > .stat-tile .st-val {{
      font-size: 1.55rem;
      font-weight: 800;
      margin-top: 0;
      line-height: 1.1;
      order: 1;
    }}
    #audit-ia-tiles > .stat-tile.audit-ia-tile .st-label,
    #audit-ia-tiles > .stat-tile.audit-ia-tile .st-val {{
      color: inherit;
    }}
    .audit-summary-deck {{
      display: flex;
      flex-direction: column;
      gap: 0.45rem;
    }}
    .audit-summary-deck > .audit-ratings-deck {{
      display: flex;
      flex-direction: column;
    }}
    .audit-summary-deck > .audit-obs-types-row-wrap {{
      display: flex;
      flex-direction: column;
    }}
    .audit-strip-row-heading {{
      margin: 0;
      padding: 0.4rem 0.65rem 0.3rem;
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.055em;
      text-transform: uppercase;
      color: #64748b;
      line-height: 1.25;
      background: rgba(248, 250, 252, 0.98);
      border-bottom: 1px solid rgba(15, 23, 42, 0.08);
      flex-shrink: 0;
    }}
    .audit-row-ia-plus-total > .audit-strip-row-heading {{
      border: 1px solid rgba(15, 23, 42, 0.1);
      border-radius: 10px 10px 0 0;
      margin-bottom: 0;
    }}
    .audit-row-ia-plus-total > .audit-strip-row-heading + .audit-ia-tiles-unified {{
      border-top: none;
      border-top-left-radius: 0;
      border-top-right-radius: 0;
    }}
    .audit-summary-deck > .audit-ratings-deck,
    .audit-summary-deck > .audit-obs-types-row-wrap {{
      border-radius: 10px;
      overflow: hidden;
      border: 1px solid rgba(15, 23, 42, 0.1);
    }}
    .audit-obs-and-filters-row {{
      display: flex;
      flex-direction: row;
      flex-wrap: wrap;
      align-items: flex-start;
      gap: 0.75rem;
      width: 100%;
    }}
    .audit-dashboard-toggles {{
      display: flex;
      align-items: center;
      gap: 0.65rem;
      flex-wrap: nowrap;
      width: 100%;
    }}
    .audit-dashboard-toggles-checks {{
      display: flex;
      align-items: center;
      gap: 0.65rem;
      flex-wrap: wrap;
      flex: 1 1 auto;
      min-width: 0;
    }}
    .audit-dashboard-toggles .audit-obs-revdate-lbl {{
      margin-inline-start: auto;
      flex-shrink: 0;
    }}
    .audit-deck-filename {{
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--text);
      word-break: break-all;
    }}
    .audit-deck-modal-panel {{
      width: min(72rem, calc(100vw - 2rem));
      max-height: min(92vh, 56rem);
    }}
    .audit-aging-panel.audit-deck-modal-panel.audit-deck-modal--fill-page {{
      top: 0 !important;
      left: 0 !important;
      right: 0 !important;
      bottom: 0 !important;
      transform: none !important;
      width: 100vw !important;
      width: 100dvw !important;
      height: 100vh !important;
      height: 100dvh !important;
      max-width: none !important;
      max-height: none !important;
      border-radius: 0 !important;
      border: none !important;
      box-shadow: none !important;
      z-index: 10000 !important;
      display: flex !important;
      flex-direction: column !important;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-aging-head,
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-modal-toolbar,
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-modal-viewer-heading {{
      display: none !important;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-deck-meta {{
      display: none !important;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-aging-inner {{
      max-height: none !important;
      height: 100% !important;
      flex: 1 1 auto !important;
      min-height: 0 !important;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-modal-toolbar {{
      padding: 0.4rem 0.65rem;
    }}
    .audit-deck-dashboard-exit {{
      display: none;
      align-items: center;
      margin: 0;
      padding: 0;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-dashboard-exit {{
      display: flex !important;
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      width: 100%;
      z-index: 10001;
      box-sizing: border-box;
      align-items: center;
      justify-content: flex-start;
      gap: 0.5rem;
      min-height: 2.85rem;
      padding: 0.45rem 0.75rem;
      padding-top: max(0.45rem, env(safe-area-inset-top, 0px));
      padding-left: max(0.75rem, env(safe-area-inset-left, 0px));
      padding-right: max(0.75rem, env(safe-area-inset-right, 0px));
      background: rgba(15, 23, 42, 0.94);
      border-bottom: 1px solid rgba(148, 163, 184, 0.28);
      box-shadow: 0 4px 18px rgba(15, 23, 42, 0.35);
    }}
    .locale-ar .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-dashboard-exit {{
      justify-content: flex-start;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-dashboard-btn.nav-btn {{
      font-weight: 700;
      border-radius: 8px;
      background: #2563eb;
      border: 2px solid #1d4ed8;
      color: #fff;
      box-shadow: 0 2px 10px rgba(37, 99, 235, 0.35);
      white-space: nowrap;
      flex-shrink: 0;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-dashboard-btn.nav-btn:hover {{
      background: #1d4ed8;
      border-color: #1e40af;
    }}
    .audit-deck-dashboard-btn.nav-btn {{
      font-weight: 700;
      border-radius: 0;
      background: #2563eb;
      border: 2px solid #1d4ed8;
      color: #fff;
      box-shadow: 0 2px 14px rgba(37, 99, 235, 0.4);
    }}
    .audit-deck-dashboard-btn.nav-btn:hover {{
      background: #1d4ed8;
      border-color: #1e40af;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-pptx-toolbar .audit-deck-pptx-nav {{
      border-radius: 0;
      background: #1e40af;
      border: 2px solid #2563eb;
      color: #fff;
      font-weight: 700;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-pptx-toolbar .audit-deck-pptx-nav:hover:not(:disabled) {{
      background: #2563eb;
      border-color: #3b82f6;
      color: #fff;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-pptx-toolbar .audit-deck-pptx-nav:disabled {{
      opacity: 0.42;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-pptx-zoombar .audit-deck-pptx-nav {{
      border-radius: 0;
      background: #1e40af;
      border: 2px solid #2563eb;
      color: #fff;
      font-weight: 700;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-pptx-zoombar .audit-deck-pptx-nav:hover:not(:disabled) {{
      background: #2563eb;
      border-color: #3b82f6;
      color: #fff;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-pptx-toolbar .audit-deck-pptx-status {{
      color: #e2e8f0;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-pptx-zoombar .audit-deck-pptx-zoom-lbl {{
      color: #94a3b8;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-modal-body {{
      flex: 1 1 auto !important;
      min-height: 0 !important;
      padding: 0 !important;
      padding-top: calc(2.85rem + env(safe-area-inset-top, 0px)) !important;
      overflow: hidden !important;
      box-sizing: border-box !important;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-modal-viewer {{
      min-height: 0 !important;
      flex: 1 1 auto !important;
      height: 100% !important;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-viewer-inner {{
      border: none !important;
      border-radius: 0 !important;
      /* Match Chrome built-in PDF chrome so letterboxing is less harsh */
      background: #323639 !important;
      flex: 1 1 auto !important;
      min-height: 0 !important;
      height: 100% !important;
      overflow: hidden !important;
      position: relative !important;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-viewer-inner iframe {{
      position: absolute !important;
      left: 0 !important;
      top: 0 !important;
      right: 0 !important;
      bottom: 0 !important;
      width: 100% !important;
      height: 100% !important;
      min-height: 0 !important;
      flex: none !important;
      border: none !important;
      background: #323639 !important;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-pptx-host {{
      flex: 1 1 auto !important;
      min-height: 0 !important;
      height: 100% !important;
      padding: 0 !important;
      display: flex !important;
      flex-direction: column !important;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-pptx-canvas-root {{
      flex: 1 1 auto !important;
      min-height: 0 !important;
      height: 100% !important;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-engine-status {{
      display: none !important;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-pptx-toolbar,
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-pptx-zoombar {{
      flex-shrink: 0;
      position: relative;
      z-index: 1;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-pptx-toolbar {{
      padding-top: 0.35rem;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-svg-host {{
      min-height: 0 !important;
      flex: 1 1 auto !important;
      height: 100% !important;
      max-height: none !important;
      padding: 0.25rem;
      display: flex !important;
      flex-direction: column !important;
      align-items: center !important;
      justify-content: center !important;
      overflow: hidden !important;
      background: #0f172a !important;
      border: none !important;
    }}
    .audit-deck-modal-panel.audit-deck-modal--fill-page .audit-deck-pptx-canvas-wrap {{
      min-height: 0 !important;
      flex: 1 1 auto;
    }}
    .audit-deck-fullpage-lbl {{
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--text);
      cursor: pointer;
      user-select: none;
      margin: 0;
      white-space: nowrap;
    }}
    .audit-deck-fullpage-lbl input {{
      accent-color: #166534;
      width: 1rem;
      height: 1rem;
    }}
    .audit-deck-upload-layer {{
      display: none;
      flex-direction: column;
      align-items: stretch;
      gap: 0.65rem;
      padding: 1.1rem 0.85rem 1rem;
      border-bottom: 1px solid var(--stroke);
      background: linear-gradient(180deg, #f8fafc 0%, #fff 100%);
      flex-shrink: 0;
    }}
    .audit-deck-modal--upload-first .audit-deck-upload-layer {{
      display: flex;
    }}
    .audit-deck-modal--upload-first .audit-deck-modal-toolbar,
    .audit-deck-modal--upload-first .audit-deck-modal-body {{
      display: none !important;
    }}
    .audit-deck-upload-layer-kicker {{
      margin: 0;
      font-size: 0.68rem;
      font-weight: 800;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: #64748b;
    }}
    .audit-deck-upload-layer-title {{
      margin: 0;
      font-size: 1.05rem;
      font-weight: 700;
      color: #0f172a;
      line-height: 1.35;
    }}
    .audit-deck-upload-layer-hint {{
      margin: 0;
      font-size: 0.82rem;
      line-height: 1.45;
      color: #475569;
      max-width: 52rem;
    }}
    .audit-deck-upload-layer-browse {{
      align-self: flex-start;
      margin-top: 0.15rem;
    }}
    .audit-deck-modal-toolbar {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: flex-start;
      gap: 0.55rem;
      padding: 0.5rem 0.85rem 0.45rem;
      border-bottom: 1px solid var(--stroke);
      flex-shrink: 0;
    }}
    .audit-deck-modal-toolbar-main {{
      flex: 1 1 220px;
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
    }}
    .audit-deck-modal-hint {{
      margin: 0;
      font-size: 0.78rem;
      line-height: 1.4;
      color: #64748b;
    }}
    .audit-deck-modal-filename {{
      display: block;
    }}
    .audit-deck-modal-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.45rem;
      align-items: center;
      flex-shrink: 0;
    }}
    .audit-deck-modal-body {{
      flex: 1 1 auto;
      min-height: 0;
      display: flex;
      flex-direction: column;
      padding: 0.65rem 0.85rem 0.85rem;
      overflow: hidden;
    }}
    .audit-deck-modal-viewer-heading {{
      margin: 0 0 0.45rem;
      font-size: 0.72rem;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #475569;
      flex-shrink: 0;
    }}
    .audit-deck-viewer-inner {{
      flex: 1 1 auto;
      min-height: 0;
      border-radius: 8px;
      border: 1px dashed rgba(15, 23, 42, 0.18);
      background: #fff;
      overflow: auto;
      position: relative;
      display: flex;
      flex-direction: column;
    }}
    .audit-deck-modal-viewer {{
      min-height: min(58vh, 640px);
      display: flex;
      flex-direction: column;
    }}
    .audit-deck-viewer-inner iframe {{
      flex: 1 1 auto;
      width: 100%;
      min-height: min(52vh, 560px);
      height: 100%;
      max-height: none;
      border: none;
      display: block;
      background: #525659;
    }}
    .audit-deck-pptx-host {{
      flex: 1 1 auto;
      min-height: 0;
      display: flex;
      flex-direction: column;
      padding: 0.5rem 0.55rem 0.65rem;
      font-size: 0.82rem;
      line-height: 1.45;
      color: var(--text);
      box-sizing: border-box;
    }}
    .locale-ar .audit-deck-pptx-host {{
      direction: rtl;
    }}
    .audit-deck-deck-meta {{
      margin-bottom: 0.85rem;
      padding: 0.65rem 0.75rem;
      border-radius: 12px;
      border: 1px solid rgba(15, 23, 42, 0.1);
      background: linear-gradient(180deg, #fafbfc 0%, #f4f6f8 100%);
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
    }}
    .audit-deck-deck-meta .audit-deck-pptx-note {{
      margin: 0 0 0.5rem;
    }}
    .audit-deck-deck-meta .audit-deck-pptx-note:last-child {{
      margin-bottom: 0;
    }}
    .audit-deck-pptx-note {{
      font-size: 0.76rem;
      color: #64748b;
      line-height: 1.45;
      margin: 0;
    }}
    .audit-deck-slide {{
      margin-bottom: 0.85rem;
      border-radius: 12px;
      border: 1px solid rgba(15, 23, 42, 0.1);
      background: #fff;
      box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
      overflow: hidden;
    }}
    .audit-deck-slide:last-child {{
      margin-bottom: 0;
    }}
    .audit-deck-slide-head {{
      display: flex;
      align-items: center;
      padding: 0.5rem 0.85rem;
      background: linear-gradient(180deg, #f8fafc 0%, #eef2f6 100%);
      border-bottom: 1px solid rgba(15, 23, 42, 0.08);
    }}
    .audit-deck-slide-head h5 {{
      margin: 0;
      font-size: 0.72rem;
      font-weight: 800;
      letter-spacing: 0.07em;
      text-transform: uppercase;
      color: #475569;
    }}
    .audit-deck-slide-body {{
      padding: 0.75rem 0.85rem;
      display: flex;
      flex-direction: column;
      gap: 0.65rem;
    }}
    .audit-deck-slide-text {{
      margin: 0;
      font-size: 0.88rem;
      line-height: 1.55;
      text-align: start;
      unicode-bidi: plaintext;
      word-break: break-word;
    }}
    .audit-deck-slide-media {{
      width: 100%;
      border-radius: 10px;
      background: #e2e8f0;
      border: 1px solid rgba(15, 23, 42, 0.08);
      padding: 0.35rem;
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 120px;
    }}
    .locale-ar .audit-deck-slide-media {{
      direction: ltr;
    }}
    .audit-deck-slide-imgs {{
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
      width: 100%;
      align-items: center;
    }}
    .audit-deck-slide-imgs img {{
      display: block;
      width: auto;
      max-width: 100%;
      max-height: min(68vh, 520px);
      height: auto;
      object-fit: contain;
      border-radius: 8px;
      background: #f1f5f9;
      border: 1px solid rgba(15, 23, 42, 0.08);
    }}
    .audit-deck-slide-empty {{
      margin: 0;
      text-align: center;
      color: #94a3b8;
      font-size: 0.85rem;
    }}
    .audit-deck-thumb {{
      display: block;
      width: 100%;
      max-width: 280px;
      max-height: min(40vh, 280px);
      margin: 0 auto;
      height: auto;
      object-fit: contain;
      border-radius: 8px;
      border: 1px solid rgba(15, 23, 42, 0.1);
      background: #f1f5f9;
    }}
    .audit-deck-pptx-canvas-root {{
      display: flex;
      flex-direction: column;
      gap: 0.55rem;
      width: 100%;
      flex: 1 1 auto;
      min-height: 0;
    }}
    .audit-deck-pptx-toolbar {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 0.45rem;
      padding: 0.35rem 0.25rem;
    }}
    .audit-deck-pptx-toolbar .audit-deck-pptx-nav {{
      font-family: inherit;
      font-size: 0.78rem;
      font-weight: 600;
      padding: 0.38rem 0.85rem;
      border-radius: 8px;
      border: 1px solid rgba(15, 23, 42, 0.14);
      background: #fff;
      color: var(--text);
      cursor: pointer;
      transition: background 0.15s ease, border-color 0.15s ease;
    }}
    .audit-deck-pptx-toolbar .audit-deck-pptx-nav:hover:not(:disabled) {{
      background: #f1f5f9;
      border-color: rgba(15, 23, 42, 0.22);
    }}
    .audit-deck-pptx-toolbar .audit-deck-pptx-nav:disabled {{
      opacity: 0.42;
      cursor: not-allowed;
    }}
    .audit-deck-pptx-toolbar .audit-deck-pptx-status {{
      font-size: 0.8rem;
      font-weight: 800;
      font-variant-numeric: tabular-nums;
      color: #475569;
      flex: 1 1 auto;
      text-align: center;
      min-width: 4rem;
    }}
    .audit-deck-pptx-zoombar {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: center;
      gap: 0.35rem;
      padding: 0 0.25rem 0.15rem;
    }}
    .audit-deck-pptx-zoombar .audit-deck-pptx-zoom-lbl {{
      font-size: 0.76rem;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
      color: #64748b;
      min-width: 3.2rem;
      text-align: center;
    }}
    .audit-deck-pptx-zoombar .audit-deck-pptx-nav {{
      padding: 0.32rem 0.62rem;
      min-width: 2.25rem;
    }}
    .audit-deck-pptx-canvas-wrap {{
      width: 100%;
      min-width: 0;
      flex: 1 1 auto;
      min-height: min(64vh, 820px);
      overflow: auto;
      border-radius: 12px;
      border: 1px solid rgba(15, 23, 42, 0.1);
      background: #e2e8f0;
      display: flex;
      justify-content: center;
      align-items: center;
      padding: 0.5rem;
      box-sizing: border-box;
    }}
    .audit-deck-pptx-canvas {{
      display: block;
      max-width: 100%;
      height: auto;
      background: #fff;
      border-radius: 8px;
      box-shadow: 0 2px 12px rgba(15, 23, 42, 0.08);
    }}
    .audit-deck-svg-host {{
      width: 100%;
      min-width: 0;
      flex: 1 1 auto;
      min-height: min(64vh, 820px);
      max-height: none;
      overflow: hidden;
      border-radius: 12px;
      border: 1px solid rgba(15, 23, 42, 0.1);
      background: #f8fafc;
      box-sizing: border-box;
      padding: 0.35rem;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
    }}
    .locale-ar .audit-deck-svg-host {{
      direction: rtl;
    }}
    .audit-deck-engine-status {{
      margin: 0 0 0.45rem;
      padding: 0.35rem 0.5rem;
      border-radius: 8px;
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: #0f766e;
      background: rgba(20, 184, 166, 0.12);
      border: 1px solid rgba(13, 148, 136, 0.25);
    }}
    .audit-dashboard-toggles-checks > .audit-obs-aging-toggle,
    .audit-deck-attach-corner .audit-obs-aging-toggle {{
      border-left: 3px solid #1e3a5f;
      background: #0d1b2a;
      border-color: #1e3a5f;
      color: #ffffff;
      transition: background 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
    }}
    .audit-dashboard-toggles-checks > .audit-obs-aging-toggle input,
    .audit-deck-attach-corner .audit-obs-aging-toggle input {{
      accent-color: #3b82f6;
    }}
    .audit-dashboard-toggles-checks > .audit-obs-aging-toggle:has(input:checked),
    .audit-deck-attach-corner .audit-obs-aging-toggle:has(input:checked) {{
      background: #0d1b2a;
      border-color: #2563eb;
      box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.28);
    }}
    .audit-dashboard-toggles-checks > .audit-obs-aging-toggle:has(input:focus-visible),
    .audit-deck-attach-corner .audit-obs-aging-toggle:has(input:focus-visible) {{
      box-shadow: 0 0 0 2px rgba(34, 197, 94, 0.35);
    }}
    /* Audit committee report toggle: larger square blue checkbox only */
    .audit-deck-attach-corner .audit-obs-aging-toggle input#audit-deck-attach-cb,
    .audit-deck-attach-corner .audit-obs-aging-toggle input#audit-high-risk-cb,
    .audit-deck-attach-corner .audit-obs-aging-toggle input#audit-tga-violations-cb,
    .audit-deck-attach-corner .audit-obs-aging-toggle input#audit-missing-vehicle-cb,
    .audit-deck-attach-corner .audit-obs-aging-toggle input#audit-internal-audit-quarterly-cb,
    .audit-deck-attach-corner .audit-obs-aging-toggle input#audit-special-assignment-cb,
    .audit-deck-attach-corner .audit-obs-aging-toggle input#audit-additional-notes-cb {{
      -webkit-appearance: none;
      appearance: none;
      width: 1.35rem;
      height: 1.35rem;
      min-width: 1.35rem;
      min-height: 1.35rem;
      aspect-ratio: 1 / 1;
      flex-shrink: 0;
      border-radius: 0 !important;
      -webkit-border-radius: 0;
      border: 2px solid #3b82f6;
      background: #0d1b2a;
      box-sizing: border-box;
      padding: 0;
      margin: 0;
      overflow: hidden;
      accent-color: #2563eb;
    }}
    .audit-deck-attach-corner .audit-obs-aging-toggle input#audit-deck-attach-cb:checked,
    .audit-deck-attach-corner .audit-obs-aging-toggle input#audit-high-risk-cb:checked,
    .audit-deck-attach-corner .audit-obs-aging-toggle input#audit-tga-violations-cb:checked,
    .audit-deck-attach-corner .audit-obs-aging-toggle input#audit-missing-vehicle-cb:checked,
    .audit-deck-attach-corner .audit-obs-aging-toggle input#audit-internal-audit-quarterly-cb:checked,
    .audit-deck-attach-corner .audit-obs-aging-toggle input#audit-special-assignment-cb:checked,
    .audit-deck-attach-corner .audit-obs-aging-toggle input#audit-additional-notes-cb:checked {{
      border-radius: 0 !important;
      -webkit-border-radius: 0;
      background: #2563eb url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12'%3E%3Cpath fill='none' stroke='%23fff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' d='M2.5 6l2.5 2.5L9.5 3'/%3E%3C/svg%3E") center / 68% no-repeat;
      border-color: #1d4ed8;
    }}
    .audit-deck-attach-corner .audit-obs-aging-toggle:has(#audit-deck-attach-cb:focus-visible),
    .audit-deck-attach-corner .audit-obs-aging-toggle:has(#audit-high-risk-cb:focus-visible),
    .audit-deck-attach-corner .audit-obs-aging-toggle:has(#audit-tga-violations-cb:focus-visible),
    .audit-deck-attach-corner .audit-obs-aging-toggle:has(#audit-missing-vehicle-cb:focus-visible),
    .audit-deck-attach-corner .audit-obs-aging-toggle:has(#audit-internal-audit-quarterly-cb:focus-visible),
    .audit-deck-attach-corner .audit-obs-aging-toggle:has(#audit-special-assignment-cb:focus-visible),
    .audit-deck-attach-corner .audit-obs-aging-toggle:has(#audit-additional-notes-cb:focus-visible) {{
      box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.45);
    }}
    .audit-obs-filters-col {{
      flex: 1 1 360px;
      min-width: 0;
    }}
    .audit-obs-names-col {{
      flex: 1 1 220px;
      min-width: 0;
      align-self: stretch;
      display: flex;
      flex-direction: column;
    }}
    .audit-obs-and-filters-row.audit-list-expanded {{
      align-items: stretch;
    }}
    .audit-obs-and-filters-row.audit-list-expanded .audit-obs-filters-col {{
      flex: 1 1 100%;
      max-width: 100%;
    }}
    .audit-obs-and-filters-row.audit-list-expanded .audit-obs-names-col {{
      flex: 1 1 100%;
      max-width: 100%;
    }}
    .audit-obs-filter-toolbar.file-filter-toolbar {{
      display: flex;
      flex-direction: row;
      flex-wrap: nowrap;
      gap: 0.5rem;
      align-items: flex-end;
      margin-top: 0;
      width: 100%;
      overflow-x: auto;
      padding-bottom: 0.15rem;
    }}
    .audit-obs-filter-toolbar.file-filter-toolbar .audit-dim-filter-block {{
      --audit-filt-accent: #6a1b9a;
      --audit-filt-surface: #f3e5f5;
      --audit-filt-border: #ce93d8;
    }}
    .audit-obs-filter-toolbar.file-filter-toolbar .audit-dim-filter-block[data-audit-dim="d"] {{
      --audit-filt-accent: #5d4037;
      --audit-filt-surface: #fbe9e7;
      --audit-filt-border: #bcaaa4;
    }}
    .audit-obs-filter-toolbar.file-filter-toolbar .audit-dim-filter-block {{
      display: flex;
      flex-direction: column;
      align-items: stretch;
      gap: 0.32rem;
      flex: 1 1 0;
      min-width: 0;
      margin: 0;
      padding: 0;
      border-radius: 10px;
      background: #ffffff;
      border: 1px solid var(--audit-filt-border, var(--stroke));
      border-left: 3px solid var(--audit-filt-accent, var(--accent));
      box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
      box-sizing: border-box;
      overflow: hidden;
    }}
    .audit-obs-filter-toolbar.file-filter-toolbar .audit-dim-filter-head {{
      display: flex;
      flex-direction: row;
      align-items: flex-start;
      justify-content: space-between;
      gap: 0.35rem;
      min-width: 0;
      padding: 0.45rem 0.55rem 0.35rem;
      background: var(--audit-filt-surface, #f8fafc);
      border-bottom: 1px solid var(--audit-filt-border, var(--stroke));
    }}
    .audit-obs-filter-toolbar.file-filter-toolbar .audit-dim-filter-title {{
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--audit-filt-accent, var(--muted));
      line-height: 1.25;
      flex: 1 1 auto;
      min-width: 0;
    }}
    .audit-obs-filter-toolbar.file-filter-toolbar .audit-dim-filter-quick {{
      display: flex;
      flex-direction: column;
      gap: 0.2rem;
      flex-shrink: 0;
      align-items: stretch;
    }}
    .audit-obs-filter-toolbar.file-filter-toolbar .audit-dim-quick-btn {{
      margin: 0;
      padding: 0.12rem 0.28rem;
      font-family: inherit;
      font-size: 0.58rem;
      font-weight: 600;
      letter-spacing: 0.02em;
      text-transform: uppercase;
      line-height: 1.2;
      border-radius: 6px;
      border: 1px solid var(--audit-filt-border, var(--stroke));
      background: #ffffff;
      color: var(--audit-filt-accent, var(--text));
      cursor: pointer;
      white-space: nowrap;
    }}
    .audit-obs-filter-toolbar.file-filter-toolbar .audit-dim-quick-btn:hover {{
      background: var(--audit-filt-surface, #f8fafc);
    }}
    .audit-obs-filter-toolbar.file-filter-toolbar .audit-dim-quick-btn:focus-visible {{
      outline: none;
      box-shadow: 0 0 0 2px rgba(106, 27, 154, 0.28);
    }}
    .audit-obs-filter-toolbar.file-filter-toolbar select {{
      width: 100%;
      min-width: 0;
      box-sizing: border-box;
      flex: 1 1 auto;
      background: #ffffff;
      color: var(--text);
      border: none;
      border-radius: 0;
      padding: 0.45rem 0.55rem 0.55rem;
      font-family: inherit;
      font-size: 0.8rem;
      font-weight: 500;
    }}
    .audit-obs-filter-toolbar.file-filter-toolbar select:focus {{
      outline: none;
      border-color: var(--audit-filt-accent, var(--accent));
      box-shadow: 0 0 0 2px rgba(106, 27, 154, 0.18);
    }}
    .audit-obs-filter-toolbar.file-filter-toolbar select[multiple] {{
      min-height: 6.25rem;
      padding-top: 0.35rem;
      padding-bottom: 0.35rem;
    }}
    .brand-context-aside > #brand-company-filter-host.file-filter-toolbar {{
      gap: 0;
      padding-bottom: 0;
      margin: 0;
    }}
    .brand-context-aside > #brand-company-filter-host .audit-dim-filter-block {{
      --audit-filt-accent: #6a1b9a;
      --audit-filt-surface: #f3e5f5;
      --audit-filt-border: #ce93d8;
      gap: 0.22rem;
      padding: 0.3rem 0.38rem 0.35rem;
      border-radius: 8px;
      border: 1px solid rgba(15, 23, 42, 0.12);
      border-left: 1px solid rgba(15, 23, 42, 0.12);
      box-shadow: none;
    }}
    .brand-context-aside > #brand-company-filter-host .audit-dim-filter-block--brand-sc {{
      --audit-filt-accent: #64748b;
      --audit-filt-surface: #ffffff;
      --audit-filt-border: rgba(15, 23, 42, 0.12);
      gap: 0;
      padding: 0;
      background: #ffffff;
      border: 1px solid rgba(15, 23, 42, 0.14);
      border-left: 1px solid rgba(15, 23, 42, 0.14);
      border-radius: 8px;
      overflow: hidden;
    }}
    .brand-context-aside > #brand-company-filter-host .audit-dim-filter-block--brand-sc select[multiple] {{
      min-height: 4.5rem;
      max-height: 7.5rem;
      padding: 0.28rem 0.4rem;
      border: none;
      border-radius: 0;
      background: #ffffff;
      font-size: 0.74rem;
      font-weight: 600;
      color: #0f172a;
    }}
    .brand-context-aside > #brand-company-filter-host .audit-dim-filter-block--brand-sc select[multiple]:focus {{
      border: none;
      box-shadow: inset 0 0 0 2px rgba(15, 23, 42, 0.12);
    }}
    .brand-context-aside > #brand-company-filter-host .audit-dim-filter-head {{
      gap: 0.28rem;
    }}
    .brand-context-aside > #brand-company-filter-host .audit-dim-filter-quick.audit-dim-filter-quick--collapsed {{
      display: none !important;
    }}
    .brand-context-aside > #brand-company-filter-host .audit-dim-filter-head.audit-dim-filter-head--toggle-quick {{
      cursor: pointer;
      user-select: none;
    }}
    .brand-context-aside > #brand-company-filter-host .audit-dim-filter-head.audit-dim-filter-head--toggle-quick:hover .audit-dim-filter-title {{
      color: #6a1b9a;
    }}
    .brand-context-aside > #brand-company-filter-host .audit-dim-filter-title {{
      font-size: 0.58rem;
      letter-spacing: 0.03em;
      color: #6a1b9a;
    }}
    .brand-context-aside > #brand-company-filter-host .audit-dim-filter-quick {{
      gap: 0.15rem;
    }}
    .brand-context-aside > #brand-company-filter-host .audit-dim-quick-btn {{
      font-size: 0.5rem;
      padding: 0.06rem 0.22rem;
      color: #6a1b9a;
      border-color: #ce93d8;
      background: #ffffff;
    }}
    .brand-context-aside > #brand-company-filter-host .audit-dim-quick-btn:hover {{
      background: #f3e5f5;
    }}
    .brand-context-aside > #brand-company-filter-host .audit-dim-quick-btn:focus-visible {{
      box-shadow: 0 0 0 2px rgba(15, 23, 42, 0.12);
    }}
    .brand-context-aside > #brand-company-filter-host select {{
      font-size: 0.72rem;
      padding: 0.22rem 0.32rem;
      border-color: rgba(15, 23, 42, 0.14);
    }}
    .brand-context-aside > #brand-company-filter-host select:focus {{
      border-color: rgba(15, 23, 42, 0.35);
      box-shadow: 0 0 0 2px rgba(15, 23, 42, 0.08);
    }}
    .brand-context-aside > #brand-company-filter-host select[multiple] {{
      min-height: 3.75rem;
      max-height: 7rem;
      padding-top: 0.22rem;
      padding-bottom: 0.22rem;
    }}
    .brand-context-aside > #brand-company-filter-host.brand-company-filter-host--compact select[multiple] {{
      min-height: 2rem;
      max-height: 3.25rem;
      padding-top: 0.12rem;
      padding-bottom: 0.12rem;
    }}
    .audit-obs-types-row-wrap {{
      width: 100%;
    }}
    .audit-obs-types-row-wrap .audit-box-obs-types {{
      width: 100%;
      min-width: 0;
    }}
    .audit-total-aside {{
      align-self: stretch;
    }}
    .audit-total-aside .audit-total-compact {{
      margin: 0;
      min-height: 0;
      height: 100%;
      padding: 0.55rem 0.65rem;
      border-radius: 12px;
      position: relative;
      overflow: hidden;
      box-shadow: none;
      background: var(--total-box-bg);
      border: 1px solid var(--total-box-border);
    }}
    .audit-total-aside .audit-total-card-btn {{
      cursor: pointer;
      transition: border-color 0.2s, box-shadow 0.2s, transform 0.15s;
      outline: none;
    }}
    .audit-total-aside .audit-total-card-btn:hover {{
      transform: none;
      background: #1e293b;
    }}
    .audit-total-aside .audit-total-card-btn:focus-visible {{
      box-shadow: 0 0 0 2px hsla(var(--dyn-h1), 65%, 55%, 0.35);
    }}
    .audit-total-aside .audit-total-card-btn.audit-tile-active {{
      z-index: 2;
      border-color: rgba(255, 255, 255, 0.45);
      background: #172554;
      filter: brightness(1.08);
      box-shadow:
        inset 0 0 0 2px rgba(255, 255, 255, 0.95),
        inset 0 0 0 5px rgba(15, 23, 42, 0.75),
        0 0 0 1px rgba(255, 255, 255, 0.25);
    }}
    .audit-total-aside .audit-total-compact::before {{
      display: none;
    }}
    .audit-total-aside .st-label,
    .audit-total-aside .st-val,
    .audit-total-aside .audit-total-sub {{
      position: relative;
      z-index: 1;
      color: var(--total-box-text);
    }}
    .audit-total-aside .st-val {{
      font-size: 1.15rem;
      font-weight: 800;
      font-variant-numeric: tabular-nums;
      color: var(--total-box-value);
    }}
    .audit-total-aside .st-label {{
      font-size: 0.62rem;
      letter-spacing: 0.05em;
    }}
    .audit-total-aside .audit-total-sub {{
      margin-top: 0.25rem;
      font-size: 0.65rem;
    }}
    .audit-ratings-deck.audit-box-ratings,
    .audit-ratings-deck.audit-box-years,
    .audit-ratings-deck.audit-box-obs-types {{
      border: none;
      box-shadow: none;
      border-radius: 0;
      background: transparent;
      overflow: visible;
      padding: 0;
    }}
    .audit-obs-names-full {{
      position: relative;
      border-radius: 12px;
      overflow: hidden;
      border: 1px solid #ce93d8;
      box-shadow: 0 2px 12px rgba(106, 27, 154, 0.08);
      display: flex;
      flex-direction: column;
      flex: 1 1 auto;
      min-height: 6.5rem;
      min-width: 0;
      background: #ffffff;
    }}
    .audit-deck-attach-corner {{
      margin-top: auto;
      display: flex;
      flex-direction: row;
      flex-wrap: wrap;
      justify-content: flex-end;
      align-items: center;
      gap: 0.5rem;
      padding: 0.5rem 0.85rem 0.7rem;
      background: #ffffff;
      border-top: 1px solid #e9d5f5;
      box-sizing: border-box;
    }}
    .audit-obs-names-bar-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.65rem;
      width: 100%;
      min-height: 2.65rem;
      box-sizing: border-box;
      padding: 0.5rem 0.95rem;
      border-radius: 10px;
      background: #f3e5f5;
      border: 1px solid #ce93d8;
      border-left: 3px solid #6a1b9a;
      color: var(--text);
    }}
    .audit-obs-names-bar-row .audit-obs-bar-title {{
      font-weight: 700;
      font-size: 0.78rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: #6a1b9a;
      flex: 1;
      min-width: 0;
    }}
    .audit-obs-list-toggle-lbl {{
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      cursor: pointer;
      padding: 0.15rem;
    }}
    input.audit-obs-show-list-cb {{
      width: 0.9rem;
      height: 0.9rem;
      margin: 0;
      cursor: pointer;
      accent-color: #6a1b9a;
    }}
    .audit-sr-only {{
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }}
    .audit-obs-check-tools {{
      display: flex;
      align-items: center;
      gap: 0.65rem;
      margin-bottom: 0.5rem;
      flex-wrap: wrap;
    }}
    .audit-obs-notes-pick-sep {{
      display: inline-block;
      width: 1px;
      height: 0.95em;
      background: hsla(var(--dyn-h2), 55%, 40%, 0.28);
      margin: 0 0.1rem;
      flex-shrink: 0;
    }}
    .audit-obs-notes-pick-meta {{
      font-size: 0.76rem;
      font-weight: 600;
      color: var(--muted);
    }}
    button.audit-obs-notes-add-btn {{
      flex-shrink: 0;
      margin-top: 0.12rem;
      width: 1.65rem;
      height: 1.65rem;
      padding: 0;
      border-radius: 10px;
      border: 1px solid hsla(var(--dyn-h2), 65%, 55%, 0.45);
      background: linear-gradient(185deg, hsla(var(--dyn-h1), 72%, 97%, 1) 0%, hsla(var(--dyn-h2), 68%, 94%, 1) 100%);
      color: hsl(var(--dyn-h2), 55%, 28%);
      font: inherit;
      font-weight: 800;
      font-size: 1.05rem;
      line-height: 1;
      cursor: pointer;
      transition: background 0.2s, border-color 0.2s;
    }}
    button.audit-obs-notes-add-btn:hover {{
      border-color: hsla(var(--dyn-h1), 72%, 48%, 0.55);
      background: linear-gradient(185deg, hsla(var(--dyn-h1), 74%, 92%, 1) 0%, hsla(var(--dyn-h2), 70%, 90%, 1) 100%);
    }}
    button.audit-obs-notes-add-btn:focus-visible {{
      outline: 2px solid hsl(var(--dyn-h1), 55%, 48%);
      outline-offset: 2px;
    }}
    .audit-additional-notes-inline {{
      margin-top: 0.75rem;
      padding: 0.65rem 0.75rem;
      border-radius: 12px;
      border: 1px solid var(--stroke);
      background: hsla(var(--dyn-h1), 72%, 98%, 0.65);
    }}
    .audit-additional-notes-heading {{
      margin: 0 0 0.55rem;
      font-size: 0.82rem;
      font-weight: 800;
      color: hsl(var(--dyn-h2), 55%, 28%);
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    ol.audit-additional-notes-ol {{
      list-style: none;
      padding: 0;
      margin: 0;
    }}
    li.audit-additional-notes-li {{
      margin-bottom: 0.4rem;
    }}
    li.audit-additional-notes-li:last-child {{
      margin-bottom: 0;
    }}
    button.audit-additional-notes-item-btn {{
      display: flex;
      align-items: flex-start;
      gap: 0.35rem;
      width: 100%;
      text-align: start;
      padding: 0.5rem 0.65rem;
      border-radius: 12px;
      border: 1px solid var(--stroke);
      background: #ffffff;
      font: inherit;
      font-size: 0.86rem;
      line-height: 1.45;
      color: var(--text);
      cursor: pointer;
      transition: border-color 0.2s, background 0.2s;
    }}
    button.audit-additional-notes-item-btn:hover:not(:disabled) {{
      border-color: hsla(var(--dyn-h2), 65%, 55%, 0.35);
      background: hsla(var(--dyn-h1), 72%, 99%, 1);
    }}
    button.audit-additional-notes-item-btn:disabled {{
      opacity: 0.55;
      cursor: not-allowed;
    }}
    .audit-additional-notes-item-num {{
      flex-shrink: 0;
      font-weight: 800;
      color: hsl(var(--dyn-h2), 55%, 36%);
      min-width: 1.6rem;
    }}
    .audit-additional-notes-item-title {{
      flex: 1;
      min-width: 0;
      font-weight: 600;
    }}
    .audit-obs-revdate-lbl {{
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      font-size: 0.74rem;
      color: #e2e8f0;
      margin-inline-start: auto;
      background: #1f2937;
      border: 1px solid #334155;
      border-radius: 10px;
      padding: 0.28rem 0.45rem;
      cursor: pointer;
    }}
    .audit-obs-revdate-lbl input[type="date"] {{
      background: #0f172a;
      border: 1px solid #334155;
      color: #e2e8f0;
      border-radius: 8px;
      padding: 0.22rem 0.38rem;
      font: inherit;
    }}
    .audit-obs-revdate-lbl input[type="date"]:focus-visible {{
      outline: 2px solid #60a5fa;
      outline-offset: 1px;
    }}
    .audit-obs-aging-toggle {{
      display: inline-flex;
      align-items: center;
      gap: 0.38rem;
      font-size: 0.74rem;
      color: #e2e8f0;
      border: 1px solid #334155;
      border-radius: 10px;
      padding: 0.28rem 0.45rem;
      background: #1f2937;
      cursor: pointer;
    }}
    .audit-obs-aging-toggle input {{
      width: 1rem;
      height: 1rem;
      margin: 0;
      cursor: pointer;
    }}
    button.audit-obs-link-btn {{
      background: none;
      border: none;
      color: hsl(var(--dyn-h2), 55%, 42%);
      font: inherit;
      font-size: 0.76rem;
      font-weight: 600;
      cursor: pointer;
      text-decoration: underline;
      padding: 0;
    }}
    button.audit-obs-link-btn:hover {{
      color: hsl(var(--dyn-h1), 55%, 38%);
    }}
    ul.audit-obs-checklist {{
      list-style: none;
      padding: 0;
      margin: 0;
    }}
    .audit-check-li {{
      margin-bottom: 0.4rem;
    }}
    .audit-check-label {{
      display: flex;
      align-items: flex-start;
      gap: 0.55rem;
      cursor: pointer;
      padding: 0.5rem 0.65rem;
      border-radius: 12px;
      border: 1px solid var(--stroke);
      background: #ffffff;
      font-size: 0.86rem;
      line-height: 1.45;
      color: var(--text);
    }}
    .audit-check-label:hover {{
      border-color: hsla(var(--dyn-h2), 65%, 55%, 0.35);
    }}
    input.audit-obs-cb {{
      margin-top: 0.2rem;
      flex-shrink: 0;
      width: 1rem;
      height: 1rem;
      accent-color: #60a5fa;
    }}
    .audit-check-text {{
      flex: 1;
      min-width: 0;
    }}
    .audit-obs-trigger-main {{
      display: block;
      font-size: inherit;
      line-height: inherit;
      color: inherit;
    }}
    .audit-obs-trigger-meta {{
      margin-top: 0.35rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.55rem;
      width: 100%;
    }}
    .audit-obs-meta-chip {{
      display: inline-flex;
      align-items: center;
      gap: 0.25rem;
      font-size: 0.7rem;
      line-height: 1.2;
      color: var(--text);
      border: 1px solid var(--stroke);
      background: #f1f5f9;
      border-radius: 999px;
      padding: 0.15rem 0.45rem;
      white-space: nowrap;
    }}
    .audit-obs-meta-chip--rating {{
      font-weight: 700;
    }}
    .audit-obs-meta-chip--dept {{
      background: linear-gradient(165deg, rgba(5, 150, 105, 0.24), rgba(6, 95, 70, 0.42));
      border-color: rgba(16, 185, 129, 0.5);
      color: #ecfdf5;
      font-weight: 600;
    }}
    .audit-obs-meta-chip--due {{
      margin-inline-start: auto;
      background: linear-gradient(165deg, rgba(30, 64, 175, 0.35), rgba(15, 23, 42, 0.82)) !important;
      border-color: rgba(125, 211, 252, 0.78) !important;
      color: #e0f2fe !important;
    }}
    .audit-obs-cb-wrap {{
      display: flex;
      align-items: flex-start;
      flex-shrink: 0;
      cursor: pointer;
    }}
    button.audit-obs-detail-trigger {{
      flex: 1;
      min-width: 0;
      margin: 0;
      padding: 0.4rem 0.65rem;
      text-align: start;
      font: inherit;
      font-size: 0.88rem;
      line-height: 1.45;
      color: var(--text);
      background: linear-gradient(165deg, #ffffff 0%, #f1f5f9 100%);
      border: 1px solid var(--stroke);
      border-radius: 12px;
      cursor: pointer;
      transition: background 0.22s, border-color 0.22s, box-shadow 0.22s, transform 0.18s ease;
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06) inset;
    }}
    button.audit-obs-detail-trigger:hover {{
      background: linear-gradient(165deg, hsla(var(--dyn-h1), 72%, 97%, 1) 0%, #e8eef5 100%);
      border-color: hsla(var(--dyn-h2), 65%, 55%, 0.35);
      box-shadow: 0 6px 28px -8px hsla(var(--dyn-h1), 70%, 50%, 0.4);
      transform: translateY(-1px);
    }}
    button.audit-obs-detail-trigger:focus-visible {{
      outline: 2px solid hsl(var(--dyn-h2), 72%, 62%);
      outline-offset: 2px;
    }}
    .audit-obs-detail-backdrop {{
      display: none;
      position: fixed;
      inset: 0;
      z-index: 200;
      background: linear-gradient(160deg, rgba(8, 14, 28, 0.78) 0%, rgba(4, 8, 18, 0.88) 50%, rgba(6, 12, 24, 0.82) 100%);
      backdrop-filter: blur(16px) saturate(1.12);
      -webkit-backdrop-filter: blur(16px) saturate(1.12);
    }}
    @keyframes auditObsBackdropIn {{
      from {{ opacity: 0; }}
      to {{ opacity: 1; }}
    }}
    .audit-obs-detail-backdrop.audit-obs-detail-backdrop--open {{
      display: block;
      animation: auditObsBackdropIn 0.28s ease forwards;
    }}
    .audit-obs-detail-panel {{
      display: none;
      position: fixed;
      z-index: 201;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      width: min(64rem, calc(100vw - 2 * var(--page-pad)));
      max-height: min(92vh, 58rem);
      max-width: calc(100vw - 2 * var(--page-pad));
      padding: 0;
      margin: 0;
      border: none;
      border-radius: 22px;
      background: transparent;
      box-sizing: border-box;
      overflow: hidden;
      box-shadow:
        0 0 0 1px rgba(94, 234, 212, 0.18),
        0 28px 90px rgba(0, 0, 0, 0.55),
        0 0 80px -20px hsla(var(--dyn-h1), 65%, 45%, 0.35);
      pointer-events: none;
    }}
    .audit-obs-detail-panel.audit-obs-detail-panel--open {{
      display: flex;
      flex-direction: column;
      pointer-events: auto;
      animation: auditObsPanelIn 0.34s cubic-bezier(0.22, 1, 0.36, 1) forwards;
    }}
    @keyframes auditObsPanelIn {{
      from {{
        opacity: 0;
        transform: translate(-50%, -48%) scale(0.97);
      }}
      to {{
        opacity: 1;
        transform: translate(-50%, -50%) scale(1);
      }}
    }}
    .audit-obs-detail-inner {{
      flex: 1;
      min-height: 0;
      display: flex;
      flex-direction: column;
      position: relative;
      background: linear-gradient(200deg, #ffffff 0%, #f8fafc 45%, #f1f5f9 100%);
      border-radius: inherit;
    }}
    .audit-obs-detail-inner::before {{
      content: "";
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 3px;
      border-radius: 22px 22px 0 0;
      background: linear-gradient(90deg, hsl(var(--dyn-h1), 72%, 55%), hsl(var(--dyn-h2), 68%, 52%), hsl(var(--dyn-h3), 64%, 50%));
      pointer-events: none;
      z-index: 2;
    }}
    .audit-obs-detail-head {{
      position: relative;
      flex-shrink: 0;
      padding: 1.35rem 3.25rem 1rem 1.35rem;
      border-bottom: 1px solid var(--stroke);
      background: linear-gradient(185deg, hsla(var(--dyn-h1), 72%, 97%, 1) 0%, transparent 90%);
    }}
    .audit-obs-detail-title {{
      margin: 0;
      font-size: clamp(1.05rem, 2.4vw, 1.35rem);
      font-weight: 800;
      line-height: 1.3;
      letter-spacing: -0.025em;
      color: var(--text);
      padding-inline-end: 0.5rem;
      max-width: 100%;
      word-break: break-word;
    }}
    .audit-obs-detail-close {{
      position: absolute;
      top: 0.65rem;
      inset-inline-end: 0.65rem;
      width: 2.25rem;
      height: 2.25rem;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 10px;
      border: 1px solid var(--stroke);
      background: #f1f5f9;
      color: var(--text);
      font-size: 1.35rem;
      line-height: 1;
      cursor: pointer;
      transition: background 0.2s, color 0.2s, border-color 0.2s;
    }}
    .audit-obs-detail-close:hover {{
      background: #e2e8f0;
      color: var(--text);
      border-color: hsla(var(--dyn-h2), 65%, 55%, 0.35);
    }}
    .audit-obs-detail-body {{
      flex: 1;
      overflow-y: auto;
      overflow-x: hidden;
      padding: 1.25rem 1.35rem 1.65rem;
      -webkit-overflow-scrolling: touch;
      min-height: 0;
    }}
    .audit-detail-block {{
      margin-bottom: 1.35rem;
    }}
    .audit-detail-block:last-child {{
      margin-bottom: 0;
    }}
    .audit-detail-email-actions {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.65rem;
      margin: 0 0 1.15rem;
    }}
    .audit-obs-detail-email-btn {{
      font: inherit;
      font-weight: 700;
      font-size: 0.82rem;
      padding: 0.45rem 0.95rem;
      border-radius: 10px;
      border: 1px solid hsla(var(--dyn-h2), 65%, 55%, 0.45);
      background: linear-gradient(185deg, hsla(var(--dyn-h1), 72%, 96%, 1) 0%, hsla(var(--dyn-h2), 68%, 94%, 1) 100%);
      color: hsl(var(--dyn-h2), 55%, 28%);
      cursor: pointer;
      transition: background 0.2s, border-color 0.2s, opacity 0.2s;
    }}
    .audit-obs-detail-email-btn:hover:not(:disabled) {{
      border-color: hsla(var(--dyn-h1), 72%, 48%, 0.55);
      background: linear-gradient(185deg, hsla(var(--dyn-h1), 74%, 92%, 1) 0%, hsla(var(--dyn-h2), 70%, 90%, 1) 100%);
    }}
    .audit-obs-detail-email-btn:disabled {{
      opacity: 0.45;
      cursor: not-allowed;
    }}
    .audit-obs-detail-email-status {{
      font-size: 0.78rem;
      color: var(--muted);
      max-width: 100%;
      line-height: 1.45;
    }}
    .audit-detail-k {{
      margin: 0 0 0.5rem;
      font-size: 0.68rem;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.11em;
      color: hsl(var(--dyn-h2), 55%, 38%);
    }}
    .audit-detail-v {{
      margin: 0;
      font-size: 0.9rem;
      font-weight: 500;
      line-height: 1.6;
      color: var(--text);
      white-space: pre-wrap;
      word-break: break-word;
      padding: 0.75rem 0.85rem;
      border-radius: 12px;
      background: #ffffff;
      border: 1px solid var(--stroke);
    }}
    .audit-detail-v.audit-detail-v--muted {{
      color: var(--muted);
      font-style: italic;
    }}
    .audit-detail-meta-strip {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.75rem;
      margin-bottom: 1.35rem;
    }}
    .audit-detail-chip {{
      min-width: 0;
      padding: 0.75rem 0.85rem;
      border-radius: 14px;
      background: linear-gradient(165deg, #f8fafc, #f1f5f9);
      border: 1px solid var(--stroke);
      box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06);
    }}
    .audit-detail-chip-k {{
      display: block;
      font-size: 0.62rem;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: hsl(var(--dyn-h2), 55%, 38%);
      margin-bottom: 0.4rem;
    }}
    .audit-detail-chip-v {{
      display: block;
      font-size: 0.95rem;
      font-weight: 700;
      line-height: 1.45;
      color: var(--text);
      word-break: break-word;
    }}
    .audit-detail-chip-v.audit-detail-chip-v--muted {{
      color: var(--muted);
      font-weight: 500;
      font-style: italic;
    }}
    @media (max-width: 520px) {{
      .audit-detail-meta-strip {{
        grid-template-columns: 1fr;
      }}
    }}
    @media (max-width: 640px) {{
      .audit-obs-detail-panel {{
        width: calc(100vw - 1rem);
        max-width: calc(100vw - 1rem);
        max-height: calc(100vh - 1rem - env(safe-area-inset-top, 0px) - env(safe-area-inset-bottom, 0px));
        border-radius: 18px;
      }}
      .audit-obs-detail-inner::before {{
        border-radius: 18px 18px 0 0;
      }}
      .audit-obs-detail-head {{
        padding: 1.2rem 2.85rem 0.9rem 1.1rem;
      }}
      .audit-obs-detail-body {{
        padding: 1rem 1.1rem 1.35rem;
      }}
    }}
    .audit-aging-backdrop {{
      position: fixed;
      inset: 0;
      z-index: 240;
      display: none;
      background: rgba(15, 23, 42, 0.35);
      backdrop-filter: blur(10px);
    }}
    .audit-aging-panel {{
      position: fixed;
      z-index: 241;
      display: none;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      width: min(56rem, calc(100vw - 2 * var(--page-pad)));
      max-height: min(88vh, 48rem);
      border-radius: 18px;
      overflow: hidden;
      box-shadow: 0 24px 64px rgba(15, 23, 42, 0.18);
      border: 1px solid var(--stroke);
      background: #ffffff;
    }}
    .audit-aging-inner {{
      display: flex;
      flex-direction: column;
      max-height: inherit;
      min-height: 0;
      height: 100%;
    }}
    #audit-reviews-panel .audit-aging-body {{
      flex: 1 1 auto;
      min-height: 0;
      overflow: hidden;
    }}
    .audit-aging-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0.8rem 1rem;
      border-bottom: 1px solid var(--stroke);
    }}
    .audit-aging-hint {{
      margin: 0 0 0.65rem 0;
      font-size: 0.82rem;
      line-height: 1.35;
      color: #64748b;
      max-width: 52rem;
    }}
    .audit-aging-title {{
      margin: 0;
      font-size: 1rem;
      font-weight: 800;
      color: var(--text);
    }}
    .audit-deck-missing-backdrop {{
      position: fixed;
      inset: 0;
      z-index: 260;
      display: none;
      background: rgba(15, 23, 42, 0.42);
      backdrop-filter: blur(8px);
    }}
    .audit-deck-missing-panel {{
      position: fixed;
      z-index: 261;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      display: none;
      width: min(22rem, calc(100vw - 2.5rem));
      border-radius: 18px;
      border: 1px solid rgba(148, 163, 184, 0.35);
      background: linear-gradient(165deg, #ffffff 0%, #f8fafc 100%);
      box-shadow:
        0 24px 48px rgba(15, 23, 42, 0.16),
        0 0 0 1px rgba(255, 255, 255, 0.65) inset;
      overflow: hidden;
      animation: audit-deck-missing-in 0.22s ease-out;
    }}
    @keyframes audit-deck-missing-in {{
      from {{
        opacity: 0;
        transform: translate(-50%, calc(-50% + 10px)) scale(0.97);
      }}
      to {{
        opacity: 1;
        transform: translate(-50%, -50%) scale(1);
      }}
    }}
    .audit-deck-missing-inner {{
      display: flex;
      flex-direction: column;
      align-items: center;
      text-align: center;
      padding: 1.65rem 1.35rem 1.35rem;
      gap: 0.65rem;
    }}
    .audit-deck-missing-icon {{
      width: 3.4rem;
      height: 3.4rem;
      border-radius: 999px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(145deg, #eff6ff 0%, #e0e7ff 100%);
      border: 1px solid rgba(59, 130, 246, 0.22);
      color: #2563eb;
      margin-bottom: 0.15rem;
    }}
    .audit-deck-missing-icon svg {{
      width: 1.55rem;
      height: 1.55rem;
      display: block;
    }}
    .audit-deck-missing-report {{
      margin: 0;
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      color: #64748b;
      line-height: 1.35;
    }}
    .audit-deck-missing-title {{
      margin: 0;
      font-size: 1.08rem;
      font-weight: 800;
      color: #0f172a;
      line-height: 1.3;
    }}
    .audit-deck-missing-msg {{
      margin: 0 0 0.35rem;
      font-size: 0.9rem;
      line-height: 1.55;
      color: #475569;
      max-width: 18rem;
    }}
    .audit-deck-missing-ok {{
      min-width: 6.5rem;
      margin-top: 0.25rem;
      padding: 0.55rem 1.35rem;
      border-radius: 999px;
      font-weight: 700;
      background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
      border-color: #1d4ed8;
      color: #fff;
      box-shadow: 0 8px 18px rgba(37, 99, 235, 0.28);
    }}
    .audit-deck-missing-ok:hover {{
      filter: brightness(1.05);
    }}
    .audit-aging-close {{
      width: 2rem;
      height: 2rem;
      border-radius: 10px;
      border: 1px solid var(--stroke);
      background: #f1f5f9;
      color: var(--text);
      cursor: pointer;
      font-size: 1.2rem;
      line-height: 1;
    }}
    .audit-aging-body {{
      overflow: auto;
      padding: 0.7rem;
    }}
    .audit-reviews-toolbar {{
      display: flex;
      justify-content: flex-end;
      align-items: center;
      gap: 0.45rem;
      padding: 0.4rem 0.65rem 0.35rem;
      border-bottom: 1px solid var(--stroke);
    }}
    .audit-reviews-body {{
      flex: 1;
      min-height: 0;
      display: flex;
      flex-direction: column;
      padding: 0.65rem;
      overflow: hidden;
    }}
    .audit-reviews-notepad {{
      flex: 1;
      min-height: min(50vh, 22rem);
      width: 100%;
      box-sizing: border-box;
      padding: 0.85rem 1rem;
      border: 1px solid #d4c9a8;
      border-radius: 10px;
      background: #fffef6;
      color: #1e293b;
      font-family: ui-monospace, "Cascadia Code", "Consolas", system-ui, sans-serif;
      font-size: 0.92rem;
      line-height: 1.55;
      box-shadow: inset 0 1px 2px rgba(30, 41, 59, 0.06);
      resize: vertical;
    }}
    .audit-reviews-notepad:focus {{
      outline: 2px solid rgba(96, 165, 250, 0.55);
      outline-offset: 1px;
    }}
    .audit-aging-table {{
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      font-size: 0.95rem;
      color: #0f172a;
      background: rgba(241, 245, 249, 0.95);
      border-radius: 12px;
      overflow: hidden;
    }}
    .audit-aging-table th,
    .audit-aging-table td {{
      border: 1px solid rgba(148, 163, 184, 0.55);
      padding: 0.45rem 0.55rem;
      text-align: center;
    }}
    .audit-aging-table th:first-child,
    .audit-aging-table td:first-child {{
      text-align: left;
      font-weight: 700;
      background: rgba(191, 219, 254, 0.72);
    }}
    .audit-aging-th-critical {{ background: rgba(192,0,0,0.88); color:#fff; }}
    .audit-aging-th-high {{ background: rgba(255,51,0,0.86); color:#fff; }}
    .audit-aging-th-medium {{ background: rgba(255,192,0,0.9); color:#111827; }}
    .audit-aging-th-low {{ background: rgba(112,173,71,0.88); color:#fff; }}
    .audit-aging-th-total {{ background: rgba(96,165,250,0.85); color:#fff; }}
    .audit-aging-row-total td {{
      background: rgba(191, 219, 254, 0.85);
      font-weight: 800;
    }}
    #audit-plan-table.audit-aging-table,
    #audit-plan-table.audit-aging-table th,
    #audit-plan-table.audit-aging-table td {{
      background: #ffffff;
      color: var(--text);
    }}
    #audit-plan-table.audit-aging-table th:first-child,
    #audit-plan-table.audit-aging-table td:first-child {{
      text-align: left;
      font-weight: 700;
    }}
    .audit-plan-colortools {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.5rem 0.75rem;
      margin-bottom: 0.5rem;
      width: 100%;
    }}
    .audit-plan-colortools-lbl {{
      font-size: 0.78rem;
      font-weight: 700;
      color: var(--text);
    }}
    .audit-plan-cell-hint {{
      font-size: 0.72rem;
      color: var(--muted);
      line-height: 1.35;
      flex: 1 1 12rem;
      min-width: 0;
    }}
    .audit-plan-cell-fill-wrap {{
      display: inline-flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 0.45rem;
      font-size: 0.74rem;
      font-weight: 600;
      color: var(--text);
      min-width: min(100%, 24rem);
    }}
    .audit-plan-palette-title {{
      font-size: 0.7rem;
      font-weight: 700;
      color: var(--muted);
      letter-spacing: 0.01em;
      text-transform: none;
    }}
    .audit-plan-palette-toggle {{
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      font-size: 0.76rem;
      font-weight: 600;
      color: var(--text);
      cursor: pointer;
      user-select: none;
    }}
    .audit-plan-palette-toggle input {{
      accent-color: #1d4ed8;
      cursor: pointer;
    }}
    .audit-plan-palette-body {{
      display: none;
      width: 100%;
    }}
    .audit-plan-palette-body.audit-plan-palette-body--open {{
      display: block;
    }}
    .audit-plan-palette-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.28rem;
      max-width: min(100%, 27rem);
    }}
    .audit-plan-swatch-btn {{
      width: 1.25rem;
      height: 1.25rem;
      border: 1px solid rgba(148, 163, 184, 0.65);
      border-radius: 3px;
      padding: 0;
      cursor: pointer;
      background: transparent;
      box-shadow: 0 1px 1px rgba(15, 23, 42, 0.08);
    }}
    .audit-plan-swatch-btn:hover {{
      transform: translateY(-1px);
      box-shadow: 0 2px 6px rgba(15, 23, 42, 0.18);
    }}
    .audit-plan-swatch-btn.audit-plan-swatch-btn--active {{
      outline: 2px solid #0f172a;
      outline-offset: 1px;
    }}
    .audit-plan-more-colors-btn {{
      font-size: 0.74rem;
      font-weight: 600;
      color: #0f172a;
      background: #ffffff;
      border: 1px solid rgba(148, 163, 184, 0.8);
      border-radius: 7px;
      padding: 0.3rem 0.55rem;
      cursor: pointer;
    }}
    .audit-plan-more-colors-btn:disabled {{
      opacity: 0.55;
      cursor: not-allowed;
    }}
    .audit-plan-cell-fill-wrap input[type="color"] {{
      width: 0;
      height: 0;
      padding: 0;
      border: 0;
      opacity: 0;
      position: absolute;
      pointer-events: none;
    }}
    .audit-plan-cell-fill-wrap input[type="color"]:disabled {{
      opacity: 0;
    }}
    #audit-plan-table.audit-aging-table td.audit-plan-cell--selected {{
      outline: 2px solid #0f172a;
      outline-offset: -2px;
    }}
    .audit-plan-clear-all-wrap {{
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      cursor: pointer;
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--text);
      user-select: none;
    }}
    .audit-plan-clear-all-wrap input {{
      accent-color: #166534;
      cursor: pointer;
    }}
    .audit-obs-names-open {{
      flex: 1;
      display: flex;
      flex-direction: column;
      min-height: 0;
      padding: 0.75rem 0.9rem 0.85rem;
      background: hsla(var(--dyn-h3), 18%, 97%, 1);
      border-top: 1px solid hsla(var(--dyn-h2), 24%, 90%, 1);
    }}
    body.audit-list-fullscreen {{
      overflow: hidden;
    }}
    body.audit-list-fullscreen #audit-box-obs {{
      position: fixed;
      z-index: 230;
      inset: var(--page-pad);
      margin: 0;
      width: auto;
      max-width: none;
      max-height: calc(100vh - (2 * var(--page-pad)));
      border-radius: 20px;
      border: 1px solid rgba(94, 234, 212, 0.38);
      box-shadow:
        0 0 0 1px rgba(255,255,255,0.05) inset,
        0 28px 80px rgba(0, 0, 0, 0.58);
      background: linear-gradient(165deg, rgba(12, 21, 40, 0.98) 0%, rgba(8, 14, 28, 0.98) 100%);
    }}
    body.audit-list-fullscreen #audit-box-obs .audit-obs-names-bar-row {{
      border-radius: 12px 12px 0 0;
      min-height: 3rem;
      padding: 0.6rem 1rem;
    }}
    body.audit-list-fullscreen #audit-box-obs .audit-obs-names-open {{
      display: flex !important;
      padding: 0.9rem 1rem 1rem;
    }}
    body.audit-list-fullscreen #audit-box-obs .audit-deck-attach-corner {{
      background: rgba(15, 23, 42, 0.72);
      border-top-color: rgba(94, 234, 212, 0.22);
    }}
    .audit-box {{
      display: flex;
      flex-direction: column;
      min-height: 0;
    }}
    .audit-box-total .audit-total-inner {{
      flex: 1;
      margin: 0;
      display: flex;
      flex-direction: column;
      justify-content: center;
    }}
    .audit-box-total .audit-total-inner:not(.audit-total-compact) {{
      min-height: 140px;
    }}
    .audit-total-sub {{
      display: block;
      margin-top: 0.45rem;
      font-size: 0.72rem;
      font-weight: 500;
      color: var(--muted);
      line-height: 1.35;
    }}
    .audit-total-sub:empty {{
      display: none;
      margin-top: 0;
    }}
    .audit-box-ratings:not(.audit-ratings-deck),
    .audit-box-obs-types:not(.audit-ratings-deck) {{
      padding: 0;
      border-radius: 14px;
      border: 1px solid var(--stroke);
      background: var(--bg-card);
      overflow: hidden;
      backdrop-filter: blur(12px);
    }}
    .audit-rating-bar-top {{
      width: 100%;
      background: #e8eef4;
      border-bottom: 1px solid var(--stroke);
      color: var(--text);
      font-weight: 700;
      font-size: 0.82rem;
      text-align: center;
      padding: 0.55rem 0.75rem;
      line-height: 1.25;
    }}
    .audit-rating-row {{
      padding: 0;
      display: flex;
      flex-direction: row;
      flex-wrap: nowrap;
      align-items: stretch;
      gap: 0;
      width: 100%;
      overflow-x: auto;
      background: transparent;
      box-sizing: border-box;
    }}
    button.audit-rating-btn,
    .audit-rating-row .audit-rating-total-pill {{
      flex: 1 1 0;
      min-width: 4.5rem;
      max-width: none;
      min-height: 6.75rem;
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      text-align: center;
      gap: 0.35rem;
      padding: 0.65rem 0.45rem;
      border-radius: 0;
      border-right: 1px solid rgba(15, 23, 42, 0.12);
    }}
    .audit-rating-row .audit-rating-total-pill:last-child {{
      border-right: none;
    }}
    .audit-rating-total-pill {{
      background: var(--total-box-bg);
      border: none;
      font-weight: 700;
      font-size: 0.75rem;
      color: var(--total-box-text);
    }}
    .audit-rating-total-pill .audit-rating-total-n {{
      font-variant-numeric: tabular-nums;
      font-size: 1.85rem;
      font-weight: 800;
      flex-shrink: 0;
      line-height: 1.1;
      order: 1;
      color: var(--total-box-value);
    }}
    .audit-rating-total-lbl {{
      flex: 0 1 auto;
      min-width: 0;
      text-align: center;
      color: var(--total-box-text);
      overflow: hidden;
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 2;
      line-height: 1.25;
      word-break: break-word;
      font-size: 0.72rem;
      font-weight: 700;
      order: 2;
    }}
    .audit-rating-stack {{
      padding: 0.65rem;
      display: flex;
      flex-direction: column;
      gap: 0.45rem;
    }}
    #audit-obs-names-scroll {{
      flex: 1;
      min-height: 140px;
      max-height: 420px;
      overflow-y: auto;
      margin-top: 0.25rem;
    }}
    .audit-ia-tiles--nav .stat-tile {{
      cursor: pointer;
      min-width: 0;
      position: relative;
      z-index: 0;
      transition:
        border-color 0.18s ease,
        box-shadow 0.18s ease,
        filter 0.18s ease,
        opacity 0.18s ease;
      box-shadow: none !important;
      backdrop-filter: none;
    }}
    .audit-ia-tiles--nav .stat-tile::after {{
      display: none;
    }}
    .audit-ia-tiles--nav .stat-tile:hover {{
      transform: none;
      box-shadow: none !important;
    }}
    #audit-ia-tiles.audit-ia-tiles--nav:has(.stat-tile.audit-tile-active) .stat-tile:not(.audit-tile-active) {{
      opacity: 0.72;
      filter: brightness(0.88) saturate(0.92);
    }}
    #audit-ia-tiles.audit-ia-tiles--nav .stat-tile.audit-tile-active {{
      z-index: 2;
      outline: none;
      opacity: 1;
      filter: brightness(1.12) saturate(1.08);
      box-shadow:
        inset 0 0 0 2px rgba(255, 255, 255, 0.98),
        inset 0 0 0 5px rgba(15, 23, 42, 0.92),
        0 0 0 1px rgba(255, 255, 255, 0.35) !important;
    }}
    #audit-ia-tiles.audit-ia-tiles--nav .stat-tile.audit-tile-active:focus-visible {{
      box-shadow:
        inset 0 0 0 2px rgba(255, 255, 255, 0.98),
        inset 0 0 0 5px rgba(15, 23, 42, 0.92),
        0 0 0 3px rgba(56, 189, 248, 0.65) !important;
    }}
    button.audit-rating-btn {{
      background: #f1f5f9;
      border: none;
      border-right: 1px solid rgba(15, 23, 42, 0.12);
      color: inherit;
      font-weight: 600;
      font-size: 0.75rem;
      cursor: pointer;
      font-family: inherit;
      position: relative;
      z-index: 0;
      transition:
        border-color 0.18s ease,
        box-shadow 0.18s ease,
        filter 0.18s ease,
        opacity 0.18s ease;
      text-align: center;
      box-shadow: none;
    }}
    button.audit-rating-btn:hover {{
      filter: none;
      opacity: 1;
    }}
    .audit-rating-row:has(.audit-rating-active) > button.audit-rating-btn:not(.audit-rating-active) {{
      opacity: 0.72;
      filter: brightness(0.88) saturate(0.92);
    }}
    button.audit-rating-btn.audit-rating-active {{
      z-index: 2;
      outline: none;
      opacity: 1;
      filter: brightness(1.12) saturate(1.08);
      box-shadow:
        inset 0 0 0 2px rgba(255, 255, 255, 0.98),
        inset 0 0 0 5px rgba(15, 23, 42, 0.92),
        0 0 0 1px rgba(255, 255, 255, 0.35) !important;
    }}
    button.audit-rating-btn.audit-rating-active:focus-visible {{
      box-shadow:
        inset 0 0 0 2px rgba(255, 255, 255, 0.98),
        inset 0 0 0 5px rgba(15, 23, 42, 0.92),
        0 0 0 3px rgba(56, 189, 248, 0.65) !important;
    }}
    .audit-rating-btn .audit-rating-lbl,
    .audit-rating-btn .audit-rating-n {{
      color: inherit;
    }}
    .audit-rating-btn .audit-rating-lbl {{
      font-size: 0.72rem;
      font-weight: 700;
      line-height: 1.25;
      order: 2;
      max-width: 100%;
    }}
    .audit-rating-btn .audit-rating-n {{
      font-variant-numeric: tabular-nums;
      opacity: 1;
      flex-shrink: 0;
      font-size: 1.85rem;
      font-weight: 800;
      line-height: 1.1;
      order: 1;
    }}
    .audit-rating-lbl {{
      flex: 1;
      min-width: 0;
      overflow: hidden;
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 2;
      line-height: 1.2;
      word-break: break-word;
    }}
    .audit-obs-type-row {{
      width: 100%;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 0.75rem;
      background: #f1f5f9;
      border: 1px solid var(--stroke);
      color: var(--text);
      font-weight: 600;
      font-size: 0.78rem;
      padding: 0.5rem 0.75rem;
      border-radius: 4px;
      font-family: inherit;
    }}
    .audit-obs-type-row .audit-obs-type-n {{
      font-variant-numeric: tabular-nums;
      opacity: 0.95;
    }}
    .audit-obs-type-lbl {{
      flex: 1;
      min-width: 0;
      text-align: start;
    }}
    .audit-obs-heading {{
      margin: 0 0 0.5rem;
      font-size: 0.88rem;
      font-weight: 700;
      color: var(--text);
      letter-spacing: -0.02em;
    }}
    .nav a {{
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--muted);
      text-decoration: none;
      padding: 0.4rem 0.75rem;
      border-radius: 8px;
      transition: color 0.2s, background 0.2s;
    }}
    .nav a:hover {{ color: var(--text); background: hsla(var(--dyn-h1), 72%, 54%, 0.14); }}
    .nav-actions {{
      margin-left: auto;
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
      align-items: center;
    }}
    .nav-btn {{
      font-family: inherit;
      font-size: 0.78rem;
      font-weight: 600;
      color: #fff;
      background: hsla(var(--dyn-h1), 65%, 48%, 0.45);
      border: 1px solid hsla(var(--dyn-h1), 72%, 58%, 0.55);
      padding: 0.4rem 0.85rem;
      border-radius: 8px;
      cursor: pointer;
      transition: background 0.2s, border-color 0.2s;
    }}
    .nav-btn:hover {{
      background: hsla(var(--dyn-h1), 65%, 48%, 0.65);
      border-color: hsla(var(--dyn-h1), 78%, 62%, 0.75);
    }}
    .nav-download-html-lbl {{
      display: inline-flex;
      align-items: center;
      gap: 0.38rem;
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--text);
      border: 1px solid var(--stroke);
      border-radius: 10px;
      padding: 0.28rem 0.55rem 0.28rem 0.4rem;
      background: #ffffff;
      cursor: pointer;
      user-select: none;
    }}
    .nav-download-html-lbl input {{
      width: 1rem;
      height: 1rem;
      margin: 0;
      accent-color: hsl(var(--dyn-h1), 58%, 52%);
      cursor: pointer;
    }}
    .nav-download-html-lbl:hover {{
      background: hsla(var(--dyn-h1), 72%, 54%, 0.1);
      border-color: hsla(var(--dyn-h1), 40%, 75%, 1);
    }}
    .shell {{
      width: 100%;
      max-width: 100%;
      margin: 0;
      padding: 1.15rem var(--page-pad) 2.5rem;
      box-sizing: border-box;
    }}
    .stat-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 0.75rem;
      margin-bottom: 1.5rem;
    }}
    .stat-tile {{
      position: relative;
      padding: 1.1rem 1rem;
      border-radius: 16px;
      background: var(--bg-card);
      border: 1px solid var(--stroke);
      backdrop-filter: blur(12px);
      overflow: hidden;
      transition: transform 0.25s ease, box-shadow 0.25s ease;
      animation: fadeUp 0.5s ease backwards;
    }}
    .stat-tile:nth-child(1) {{ animation-delay: 0.05s; }}
    .stat-tile:nth-child(2) {{ animation-delay: 0.1s; }}
    .stat-tile:nth-child(3) {{ animation-delay: 0.15s; }}
    .stat-tile:nth-child(4) {{ animation-delay: 0.2s; }}
    .stat-tile:nth-child(5) {{ animation-delay: 0.25s; }}
    .stat-tile:nth-child(6) {{ animation-delay: 0.3s; }}
    .stat-tile:hover {{
      transform: translateY(-3px);
      box-shadow: 0 10px 28px rgba(15, 23, 42, 0.12);
    }}
    .stat-tile::after {{
      content: "";
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 3px;
      border-radius: 16px 16px 0 0;
    }}
    .st-0::after {{ background: linear-gradient(90deg, hsl(var(--dyn-h1),72%,42%), hsl(var(--dyn-h2),70%,38%)); }}
    .st-1::after {{ background: linear-gradient(90deg, hsl(var(--dyn-h2),72%,42%), hsl(var(--dyn-h3),68%,36%)); }}
    .st-2::after {{ background: linear-gradient(90deg, hsl(var(--dyn-h3),70%,40%), hsl(var(--dyn-h1),74%,38%)); }}
    .st-3::after {{ background: linear-gradient(90deg, hsl(var(--dyn-h1),68%,36%), hsl(var(--dyn-h3),70%,38%)); }}
    .st-4::after {{ background: linear-gradient(90deg, hsl(var(--dyn-h2),74%,38%), hsl(var(--dyn-h1),68%,40%)); }}
    .st-5::after {{ background: linear-gradient(90deg, hsl(var(--dyn-h3),70%,40%), hsl(var(--dyn-h2),66%,38%)); }}
    .st-label {{ display: block; font-size: 0.72rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }}
    .st-val {{ display: block; font-size: 1.5rem; font-weight: 800; margin-top: 0.35rem; font-variant-numeric: tabular-nums; }}
    section.panel {{
      margin-bottom: 1.25rem;
      padding: 1.25rem 1.35rem;
      border-radius: 20px;
      background: var(--bg-card);
      border: 1px solid var(--stroke);
      backdrop-filter: blur(14px);
      animation: fadeUp 0.55s ease backwards;
    }}
    section.panel h2 {{
      margin: 0 0 1rem;
      font-size: 1.05rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 0.5rem;
      letter-spacing: -0.02em;
    }}
    section.panel h2::before {{
      content: "";
      width: 4px;
      height: 1.15em;
      border-radius: 4px;
      background: linear-gradient(180deg, var(--accent), var(--accent2));
    }}
    .charts {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
      gap: 1.15rem;
    }}
    .chart-card {{
      height: 440px;
      min-height: 440px;
      padding: 1rem;
      border-radius: 16px;
      background: #ffffff;
      border: 1px solid var(--stroke);
      box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
    }}
    .chart-card canvas {{
      width: 100% !important;
      height: 100% !important;
      display: block;
    }}
    .table-wrap {{
      overflow-x: auto;
      border-radius: 12px;
      border: 1px solid var(--stroke);
    }}
    #preview .table-wrap {{
      max-height: min(75vh, 960px);
      overflow-y: auto;
    }}
    #preview .table-wrap thead th {{
      position: sticky;
      top: 0;
      z-index: 1;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.82rem;
      min-width: 560px;
    }}
    th, td {{
      padding: 0.65rem 0.85rem;
      text-align: start;
      vertical-align: top;
      border-bottom: 1px solid var(--stroke);
    }}
    th {{
      background: linear-gradient(180deg, #f1f5f9, #e2e8f0);
      color: #334155;
      font-weight: 600;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    tbody tr:hover td {{ background: hsla(var(--dyn-h1), 72%, 54%, 0.08); }}
    .muted {{ font-size: 0.78rem; color: var(--muted); margin-top: 0.75rem; }}
    .empty-hint {{ color: var(--muted); font-size: 0.9rem; margin: 0; }}
    p.muted {{ margin: 0; }}
    .ft-toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 1rem;
      align-items: center;
      margin-bottom: 1rem;
    }}
    .ft-toolbar label {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-size: 0.85rem;
      color: var(--muted);
    }}
    .ft-toolbar select {{
      background: #ffffff;
      border: 1px solid var(--stroke);
      color: var(--text);
      padding: 0.4rem 0.75rem;
      border-radius: 8px;
      font-family: inherit;
      min-width: 10rem;
    }}
    .ft-period-btns {{
      display: inline-flex;
      gap: 0.35rem;
      flex-wrap: wrap;
    }}
    .ft-period-btns button {{
      font-family: inherit;
      font-size: 0.78rem;
      font-weight: 600;
      padding: 0.45rem 0.85rem;
      border-radius: 8px;
      border: 1px solid var(--stroke);
      background: #ffffff;
      color: var(--muted);
      cursor: pointer;
      transition: background 0.2s, color 0.2s, border-color 0.2s;
    }}
    .ft-period-btns button:hover {{ color: var(--text); border-color: hsla(var(--dyn-h2), 65%, 55%, 0.45); }}
    .ft-period-btns button.active {{
      background: hsla(var(--dyn-h1), 72%, 54%, 0.2);
      color: var(--text);
      border-color: hsla(var(--dyn-h1), 72%, 58%, 0.45);
    }}
    .ft-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 1.15rem;
    }}
    .ft-grid .chart-card.ft-stack-card {{
      grid-column: 1 / -1;
      height: 500px;
      min-height: 500px;
    }}
    .ft-note {{ font-size: 0.78rem; color: var(--muted); margin: 0.75rem 0 0; line-height: 1.45; }}
    .file-filter-panel {{
      margin-bottom: 1rem;
      padding: 0.85rem 1rem;
      border-radius: 14px;
      border: 1px solid var(--stroke);
      background: #f8fafc;
    }}
    .file-filter-toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 1rem;
      align-items: center;
      margin-top: 0.65rem;
    }}
    .file-filter-toolbar label {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-size: 0.85rem;
      color: var(--muted);
    }}
    .file-filter-toolbar select {{
      background: #ffffff;
      border: 1px solid var(--stroke);
      color: var(--text);
      padding: 0.4rem 0.75rem;
      border-radius: 8px;
      font-family: inherit;
      min-width: 10rem;
    }}
    .file-filter-meta {{ margin: 0.35rem 0 0; }}
    .file-filter-loaded {{ margin: 0.25rem 0 0; }}
    .locale-ar th {{
      text-transform: none;
      letter-spacing: 0.02em;
    }}
    .audit-pie-section {{
      width: 100%;
      max-width: 100%;
      margin: 0 0 1.25rem;
      padding: 0;
      box-sizing: border-box;
    }}
    .audit-pie-deck {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 1rem;
      width: 100%;
      max-width: 100%;
      margin: 0;
      align-items: stretch;
    }}
    @media (max-width: 1200px) {{
      .audit-pie-deck {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
    }}
    @media (max-width: 640px) {{
      .audit-pie-deck {{
        grid-template-columns: 1fr;
      }}
    }}
    .audit-pie-card {{
      position: relative;
      border-radius: 22px;
      padding: 1rem 0.85rem 0.65rem;
      background: #ffffff;
      border: 1px solid var(--stroke);
      box-shadow: none;
      overflow: hidden;
      min-height: 0;
    }}
    .audit-pie-card-accent {{
      display: none;
    }}
    .audit-pie-card--ia .audit-pie-card-accent {{
      background: radial-gradient(circle, hsla(var(--dyn-h1), 72%, 40%, 0.28) 0%, transparent 68%);
    }}
    .audit-pie-card--rating .audit-pie-card-accent {{
      background: radial-gradient(circle, hsla(var(--dyn-h2), 70%, 38%, 0.26) 0%, transparent 68%);
    }}
    .audit-pie-card--year .audit-pie-card-accent {{
      background: radial-gradient(circle, hsla(220, 8%, 42%, 0.22) 0%, transparent 68%);
    }}
    .audit-pie-card--obs .audit-pie-card-accent {{
      background: radial-gradient(circle, hsla(var(--dyn-h3), 66%, 34%, 0.26) 0%, transparent 68%);
    }}
    .audit-pie-card--obs {{
      overflow: visible;
      padding-top: 0.75rem;
    }}
    .audit-pie-card--obs .audit-pie-title {{
      margin-bottom: 0.3rem;
    }}
    .audit-pie-card--obs .audit-pie-canvas-wrap {{
      height: 300px;
      min-height: 280px;
      max-height: 420px;
      overflow: visible;
    }}
    .audit-pie-title {{
      position: relative;
      z-index: 1;
      margin: 0 0 0.45rem;
      font-size: 0.72rem;
      font-weight: 800;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      text-align: center;
      color: #334155;
      text-shadow: none;
    }}
    .audit-pie-canvas-wrap {{
      position: relative;
      z-index: 1;
      height: 300px;
      min-height: 300px;
      width: 100%;
    }}
    .audit-pie-canvas-wrap canvas {{
      width: 100% !important;
      height: 100% !important;
      max-height: 100%;
      display: block;
    }}
  </style>
</head>
<body class="{('locale-ar' if loc == 'ar' else '')}">
  <div class="noise" aria-hidden="true"></div>
  <div class="brand-strip">
    <div class="brand-strip-inner">
      <div class="brand-logo-cluster">
      <button type="button" class="brand-logo-wrap brand-logo-btn" id="brand-logo-reset" style="display:{logo_button_display};" title="{html.escape(tr(loc, "brand_logo_reset_aria"))}" aria-label="{html.escape(tr(loc, "brand_logo_reset_aria"))}">
        <img class="brand-logo" id="brand-logo-img" src="{logo_src_attr}" alt="" decoding="async" data-default-src="{logo_src_attr}" />
      </button>
      </div>
      <aside id="brand-context-aside" class="brand-context-aside" aria-live="polite">
        <div class="brand-context-head-row">
          <span id="brand-context-kicker" class="brand-context-kicker"></span>
          <button type="button" class="brand-company-filter-reopen" id="brand-company-filter-reopen" hidden></button>
        </div>
        <div id="brand-company-filter-host" class="file-filter-toolbar audit-obs-toolbar audit-obs-filter-toolbar brand-company-filter-host" aria-label="{html.escape(tr(loc, "audit_company_label"))}"></div>
        <div id="brand-context-company-names" class="brand-context-names"></div>
      </aside>
    </div>
  </div>
  <nav class="nav" id="nav-default" style="display: {default_nav_display};" aria-label="{html.escape(tr(loc, "nav_aria_sections"))}">
    <a href="#preview">{html.escape(tr(loc, "nav_data"))}</a>
    <a href="#segment">{html.escape(tr(loc, "nav_segment"))}</a>
    <a href="#trend">{html.escape(tr(loc, "nav_trend"))}</a>
    <a href="#corr">{html.escape(tr(loc, "nav_corr"))}</a>
    <span class="nav-actions">
      <label class="nav-download-html-lbl" title="{html.escape(tr(loc, "nav_download_title"))}">
        <input type="checkbox" id="save-report-html-cb" aria-label="{html.escape(tr(loc, "nav_download_title"))}" />
        <span>{html.escape(tr(loc, "nav_download_html"))}</span>
      </label>
    </span>
  </nav>
  <main class="shell">
    <section class="audit-pie-section" id="audit-pie-section" style="display: {audit_obs_root_display};" aria-label="{html.escape(tr(loc, "audit_pie_section_aria"))}">
      <div class="audit-pie-deck">
        <article class="audit-pie-card audit-pie-card--ia">
          <div class="audit-pie-card-accent" aria-hidden="true"></div>
          <h3 class="audit-pie-title" id="audit-pie-title-ia"></h3>
          <div class="audit-pie-canvas-wrap">
            <canvas id="audit-pie-ia-status"></canvas>
          </div>
        </article>
        <article class="audit-pie-card audit-pie-card--year">
          <div class="audit-pie-card-accent" aria-hidden="true"></div>
          <h3 class="audit-pie-title" id="audit-pie-title-year"></h3>
          <div class="audit-pie-canvas-wrap">
            <canvas id="audit-pie-audit-year"></canvas>
          </div>
        </article>
        <article class="audit-pie-card audit-pie-card--rating">
          <div class="audit-pie-card-accent" aria-hidden="true"></div>
          <h3 class="audit-pie-title" id="audit-pie-title-rating"></h3>
          <div class="audit-pie-canvas-wrap">
            <canvas id="audit-pie-rating"></canvas>
          </div>
        </article>
        <article class="audit-pie-card audit-pie-card--obs">
          <div class="audit-pie-card-accent" aria-hidden="true"></div>
          <h3 class="audit-pie-title" id="audit-pie-title-obs"></h3>
          <div class="audit-pie-canvas-wrap">
            <canvas id="audit-pie-obs-type"></canvas>
          </div>
        </article>
      </div>
    </section>
    <div class="audit-top-bar" id="audit-top-bar" style="display: {audit_top_bar_display};" role="navigation" aria-label="{html.escape(tr(loc, "audit_top_bar_aria"))}">
      <div class="audit-top-inner">
        <div class="audit-row-ia-plus-total">
          <p class="audit-strip-row-heading">{html.escape(tr(loc, "audit_pie_ia_title"))}</p>
          <div class="audit-ia-tiles-unified">
            <div id="audit-ia-tiles" class="audit-ia-tiles-host audit-ia-tiles audit-ia-tiles--nav"></div>
            <div class="audit-total-aside audit-box-total">
              <div class="stat-tile st-0 audit-total-inner audit-total-compact audit-total-card-btn" id="audit-total-card" role="button" tabindex="0" aria-pressed="false" aria-label="{html.escape(tr(loc, "audit_total_card_aria"))}">
                <span class="st-label" id="audit-total-label"></span>
                <span class="st-val" id="audit-total-val">0</span>
                <span class="audit-total-sub" id="audit-total-sub"></span>
              </div>
            </div>
          </div>
        </div>
        <div class="audit-summary-deck">
          <div class="audit-ratings-deck audit-box audit-box-ratings" id="audit-box-ratings" aria-label="{html.escape(tr(loc, "audit_box_ratings_aria"))}">
            <p class="audit-strip-row-heading">{html.escape(tr(loc, "audit_rating_strip_title"))}</p>
            <div class="audit-rating-btns audit-rating-row" id="audit-rating-btns"></div>
          </div>
          <div class="audit-obs-types-row-wrap" id="audit-obs-types-row-wrap" style="display: {audit_obs_type_box_display};">
            <p class="audit-strip-row-heading">{html.escape(tr(loc, "audit_obs_type_bar_title"))}</p>
            <div class="audit-ratings-deck audit-box audit-box-obs-types" id="audit-box-obs-types" aria-label="{html.escape(tr(loc, "audit_box_obs_type_aria"))}" title="{html.escape(tr(loc, "audit_obs_type_click_hint"))}">
              <div class="audit-rating-btns audit-rating-row" id="audit-obs-type-btns"></div>
            </div>
          </div>
          <div class="audit-ratings-deck audit-box audit-box-years" id="audit-box-years" aria-label="{html.escape(tr(loc, "audit_box_years_aria"))}">
            <p class="audit-strip-row-heading">{html.escape(tr(loc, "audit_year_strip_title"))}</p>
            <div class="audit-rating-btns audit-rating-row" id="audit-year-btns"></div>
          </div>
          <div class="audit-dashboard-toggles">
            <div class="audit-dashboard-toggles-checks">
            <label class="audit-obs-aging-toggle">
              <input type="checkbox" id="audit-aging-matrix-cb" />
              <span id="audit-aging-matrix-label"></span>
            </label>
            <label class="audit-obs-aging-toggle">
              <input type="checkbox" id="audit-aging-revised-cb" />
              <span id="audit-aging-revised-label"></span>
            </label>
            <label class="audit-obs-aging-toggle">
              <input type="checkbox" id="audit-plan-status-cb" />
              <span id="audit-plan-status-label"></span>
            </label>
            <label class="audit-obs-aging-toggle">
              <input type="checkbox" id="audit-reviews-cb" />
              <span id="audit-reviews-label"></span>
            </label>
            <label class="audit-obs-aging-toggle" title="{html.escape(tr(loc, "nav_download_title"))}">
              <input type="checkbox" id="save-report-html-cb-audit" aria-label="{html.escape(tr(loc, "nav_download_title"))}" />
              <span>{html.escape(tr(loc, "audit_top_html_download_label"))}</span>
            </label>
            </div>
            <label class="audit-obs-revdate-lbl" id="audit-obs-revised-date-wrap" style="display:none">
              <span id="audit-obs-revised-date-label"></span>
              <input type="date" id="audit-obs-revised-date" />
            </label>
          </div>
          <div class="audit-obs-and-filters-row" id="audit-obs-and-filters-row">
            <div class="audit-obs-filters-col">
              <div class="file-filter-toolbar audit-obs-toolbar audit-obs-filter-toolbar" id="audit-filter-toolbar"></div>
            </div>
            <div class="audit-obs-names-col">
              <div class="audit-obs-names-full" id="audit-box-obs" aria-label="{html.escape(tr(loc, "audit_box_obs_aria"))}">
                <div class="audit-obs-names-bar-row">
                  <span class="audit-obs-bar-title" id="audit-obs-bar-title"></span>
                  <label class="audit-obs-list-toggle-lbl">
                    <input type="checkbox" id="audit-obs-show-list-cb" class="audit-obs-show-list-cb" aria-controls="audit-obs-names-panel" title="{html.escape(tr(loc, "audit_obs_names_toggle_hint"))}" />
                  </label>
                </div>
                <span id="audit-obs-bar-meta" class="audit-sr-only" aria-live="polite"></span>
                <div class="audit-obs-names-open" id="audit-obs-names-panel" style="display:none" role="region" aria-labelledby="audit-obs-bar-title">
                  <p class="audit-obs-heading" id="audit-obs-heading"></p>
                  <div class="audit-obs-check-tools" id="audit-obs-check-tools" style="display:none">
                    <button type="button" class="audit-obs-link-btn" id="audit-obs-select-all"></button>
                    <button type="button" class="audit-obs-link-btn" id="audit-obs-select-none"></button>
                    <span class="audit-obs-notes-pick-sep" aria-hidden="true"></span>
                    <span class="audit-obs-notes-pick-meta muted" id="audit-obs-notes-pick-meta"></span>
                    <button type="button" class="audit-obs-link-btn" id="audit-obs-notes-clear-picks"></button>
                  </div>
                  <div id="audit-obs-names-scroll">
                    <ul id="audit-open-list" class="audit-obs-checklist"></ul>
                    <p class="empty-hint" id="audit-open-empty" style="display:none"></p>
                  </div>
                </div>
                <div class="audit-deck-attach-corner">
                  {deck_attach_toggle_html}
                  <label class="audit-obs-aging-toggle">
                    <input type="checkbox" id="audit-additional-notes-cb" aria-controls="audit-additional-notes-inline-panel" />
                    <span id="audit-additional-notes-label"></span>
                  </label>
                </div>
                <div class="audit-additional-notes-inline" id="audit-additional-notes-inline-panel" style="display:none" role="region" aria-labelledby="audit-additional-notes-inline-heading">
                  <h4 class="audit-additional-notes-heading" id="audit-additional-notes-inline-heading">{html.escape(tr(loc, "audit_additional_notes_toggle_label"))}</h4>
                  <ol id="audit-additional-notes-ol" class="audit-additional-notes-ol"></ol>
                  <p class="empty-hint" id="audit-additional-notes-empty" style="display:none"></p>
                </div>
              </div>
            </div>
          </div>
        </div>
        <p class="muted" id="audit-truncated-note" style="display:none;margin-top:0.75rem;"></p>
      </div>
    </div>
    <div id="default-stat-grid" class="stat-grid" style="display: {default_stat_grid_display};">{stat_tiles}</div>

    <section id="alerts" class="panel" style="display:none">
      <h2>{html.escape(tr(loc, "panel_alerts"))}</h2>
      {to_html_table(alert_table, max_rows=20, empty_message=tr(loc, "table_no_data"))}
    </section>

    <section id="charts" class="panel" style="display:none">
      <h2>{html.escape(tr(loc, "panel_charts"))}</h2>
      <div id="file-filter-panel" class="file-filter-panel" style="display:none">
        <p class="muted file-filter-hint" id="file-filter-hint"></p>
        <p class="muted file-filter-meta" id="file-filter-match"></p>
        <p class="muted file-filter-loaded" id="file-filter-loaded" style="display:none"></p>
        <div class="file-filter-toolbar" id="file-filter-toolbar"></div>
      </div>
      <div class="charts">
        <div class="chart-card"><canvas id="segmentChart"></canvas></div>
        <div class="chart-card"><canvas id="trendChart"></canvas></div>
      </div>
    </section>

    <section id="finance-trends" class="panel" style="display:none">
      <h2>{html.escape(tr(loc, "panel_finance_trends"))}</h2>
      <p id="finance-trends-unavailable" class="muted" style="display:none"></p>
      <div id="finance-trends-body" style="display:none">
        <p class="muted ft-metric-hint" id="ft-metric-hint"></p>
        <div class="ft-toolbar">
          <label>{html.escape(tr(loc, "ft_category_label"))}
            <select id="ft-category" aria-label="{html.escape(tr(loc, "ft_category_aria"))}"></select>
          </label>
          <div class="ft-period-btns" role="group" aria-label="{html.escape(tr(loc, "ft_period_group"))}">
            <button type="button" class="active" data-ft-period="month">{html.escape(tr(loc, "ft_monthly"))}</button>
            <button type="button" data-ft-period="quarter">{html.escape(tr(loc, "ft_quarterly"))}</button>
            <button type="button" data-ft-period="year">{html.escape(tr(loc, "ft_annual"))}</button>
          </div>
        </div>
        <div class="ft-grid">
          <div class="chart-card"><canvas id="ftLineChart"></canvas></div>
          <div class="chart-card"><canvas id="ftBarChart"></canvas></div>
          <div class="chart-card ft-stack-card"><canvas id="ftStackChart"></canvas></div>
        </div>
        <p class="ft-note" id="ft-stack-note">{html.escape(tr(loc, "ft_stack_note"))}</p>
      </div>
    </section>

    <section id="preview" class="panel">
      <h2>{html.escape(tr(loc, "panel_preview"))}</h2>
      {to_html_table(df_work, max_rows=None, empty_message=tr(loc, "table_no_data"))}
    </section>

    <section id="segment" class="panel">
      <h2>{html.escape(tr(loc, "panel_segment"))}</h2>
      {to_html_table(segment_table, max_rows=15, empty_message=tr(loc, "table_no_data"))}
    </section>

    <section id="trend" class="panel">
      <h2>{html.escape(tr(loc, "panel_trend"))}</h2>
      {to_html_table(trend_table, max_rows=20, empty_message=tr(loc, "table_no_data"))}
    </section>

    <section id="corr" class="panel">
      <h2>{html.escape(tr(loc, "panel_corr"))}</h2>
      {to_html_table(corr_table, max_rows=10, empty_message=tr(loc, "table_no_data"))}
      <p class="muted">{html.escape(tr(loc, "corr_footer"))}</p>
    </section>
    <div class="audit-obs-detail-backdrop" id="audit-obs-detail-backdrop" style="display:none" aria-hidden="true"></div>
    <div class="audit-obs-detail-panel" id="audit-obs-detail-panel" role="dialog" aria-modal="true" aria-labelledby="audit-obs-detail-title" aria-label="{html.escape(tr(loc, "audit_obs_detail_aria"))}" style="display:none" aria-hidden="true">
      <div class="audit-obs-detail-inner">
        <div class="audit-obs-detail-head">
          <button type="button" class="audit-obs-detail-close" id="audit-obs-detail-close" aria-label="{html.escape(tr(loc, "audit_obs_detail_close"))}">×</button>
          <h3 class="audit-obs-detail-title" id="audit-obs-detail-title"></h3>
        </div>
        <div class="audit-obs-detail-body">
          <div class="audit-detail-meta-strip" id="audit-obs-detail-meta-strip">
            <div class="audit-detail-chip" id="audit-obs-detail-chip-due">
              <span class="audit-detail-chip-k" id="audit-obs-detail-k-due"></span>
              <span class="audit-detail-chip-v" id="audit-obs-detail-v-due"></span>
            </div>
            <div class="audit-detail-chip" id="audit-obs-detail-chip-rt">
              <span class="audit-detail-chip-k" id="audit-obs-detail-k-rt"></span>
              <span class="audit-detail-chip-v" id="audit-obs-detail-v-rt"></span>
            </div>
          </div>
          <div class="audit-detail-email-actions audit-obs-detail-email-wrap" id="audit-obs-detail-email-wrap" hidden>
            <button type="button" class="audit-obs-detail-email-btn" id="audit-obs-detail-send-email"></button>
            <span class="audit-obs-detail-email-status" id="audit-obs-detail-email-status" aria-live="polite"></span>
            <button type="button" class="audit-obs-detail-email-btn" id="audit-obs-detail-download-ppt"></button>
            <span class="audit-obs-detail-email-status" id="audit-obs-detail-download-status" aria-live="polite"></span>
          </div>
          <section class="audit-detail-block">
            <h4 class="audit-detail-k">{html.escape(tr(loc, "audit_obs_detail_summary"))}</h4>
            <p class="audit-detail-v" id="audit-obs-detail-v-sum"></p>
          </section>
          <section class="audit-detail-block">
            <h4 class="audit-detail-k">{html.escape(tr(loc, "audit_obs_detail_recommendation"))}</h4>
            <p class="audit-detail-v" id="audit-obs-detail-v-rec"></p>
          </section>
        </div>
      </div>
    </div>
    <div class="audit-aging-backdrop" id="audit-aging-backdrop" style="display:none" aria-hidden="true"></div>
    <div class="audit-aging-panel" id="audit-aging-panel" role="dialog" aria-modal="true" aria-hidden="true" style="display:none">
      <div class="audit-aging-inner">
        <div class="audit-aging-head">
          <h3 class="audit-aging-title" id="audit-aging-title"></h3>
          <button type="button" class="audit-aging-close" id="audit-aging-close" aria-label="Close">×</button>
        </div>
        <p class="audit-aging-hint" id="audit-aging-hint" hidden></p>
        <div class="audit-aging-body">
          <table class="audit-aging-table" id="audit-aging-table">
            <thead id="audit-aging-head-row"></thead>
            <tbody id="audit-aging-body-rows"></tbody>
          </table>
        </div>
      </div>
    </div>
    <div class="audit-aging-backdrop" id="audit-plan-backdrop" style="display:none" aria-hidden="true"></div>
    <div class="audit-aging-panel" id="audit-plan-panel" role="dialog" aria-modal="true" aria-hidden="true" style="display:none">
      <div class="audit-aging-inner">
        <div class="audit-aging-head">
          <h3 class="audit-aging-title" id="audit-plan-title"></h3>
          <button type="button" class="audit-aging-close" id="audit-plan-close" aria-label="Close">×</button>
        </div>
        <div class="audit-aging-body">
          <div class="audit-plan-toolbar" style="display:flex;justify-content:space-between;gap:0.45rem;align-items:center;margin-bottom:0.55rem;flex-wrap:wrap;">
            <div style="display:flex;gap:0.55rem;align-items:center;flex-wrap:wrap;">
            <button type="button" class="nav-btn audit-plan-add-row-btn" id="audit-plan-add-row"></button>
            <label class="audit-plan-clear-all-wrap" id="audit-plan-clear-all-wrap">
              <input type="checkbox" id="audit-plan-clear-all-cb" />
              <span id="audit-plan-clear-all-label"></span>
            </label>
            </div>
            <div style="display:flex;gap:0.45rem;align-items:center;flex-wrap:wrap;">
              <button type="button" class="nav-btn" id="audit-plan-upload-btn"></button>
              <input type="file" id="audit-plan-upload-file" accept=".csv,.xlsx,.xls,.xlsm,.json,.pptx" style="display:none" aria-hidden="true" />
              <button type="button" class="nav-btn" id="audit-plan-download-ppt"></button>
            </div>
          </div>
          <div class="audit-plan-colortools" id="audit-plan-colortools-wrap">
            <span class="audit-plan-colortools-lbl" id="audit-plan-colortools-label"></span>
            <span class="audit-plan-cell-hint" id="audit-plan-cell-hint"></span>
            <label class="audit-plan-cell-fill-wrap" id="audit-plan-cell-fill-wrap">
              <span id="audit-plan-cell-fill-lbl"></span>
              <label class="audit-plan-palette-toggle" id="audit-plan-palette-toggle">
                <input type="checkbox" id="audit-plan-palette-cb" />
                <span id="audit-plan-palette-toggle-lbl">Show colors</span>
              </label>
              <div class="audit-plan-palette-body" id="audit-plan-palette-body">
                <span class="audit-plan-palette-title" id="audit-plan-theme-colors-lbl">Theme Colors</span>
                <div class="audit-plan-palette-row" id="audit-plan-theme-swatches"></div>
                <span class="audit-plan-palette-title" id="audit-plan-standard-colors-lbl">Standard Colors</span>
                <div class="audit-plan-palette-row" id="audit-plan-standard-swatches"></div>
                <button type="button" class="audit-plan-more-colors-btn" id="audit-plan-more-colors-btn">More Colors...</button>
              </div>
              <input type="color" id="audit-plan-cell-color" value="#ffffff" disabled />
            </label>
            <button type="button" class="nav-btn" id="audit-plan-cell-apply">Apply</button>
            <button type="button" class="nav-btn" id="audit-plan-col-reset"></button>
          </div>
          <table class="audit-aging-table" id="audit-plan-table">
            <thead id="audit-plan-head-row"></thead>
            <tbody id="audit-plan-body-rows"></tbody>
          </table>
        </div>
      </div>
    </div>
    <div class="audit-aging-backdrop" id="audit-reviews-backdrop" style="display:none" aria-hidden="true"></div>
    <div class="audit-aging-panel" id="audit-reviews-panel" role="dialog" aria-modal="true" aria-hidden="true" style="display:none">
      <div class="audit-aging-inner">
        <div class="audit-aging-head">
          <h3 class="audit-aging-title" id="audit-reviews-title"></h3>
          <button type="button" class="audit-aging-close" id="audit-reviews-close" aria-label="Close">×</button>
        </div>
        <div class="audit-reviews-toolbar">
          <button type="button" class="nav-btn" id="audit-reviews-download"></button>
        </div>
        <div class="audit-aging-body audit-reviews-body">
          <textarea id="audit-reviews-textarea" class="audit-reviews-notepad" wrap="soft"></textarea>
        </div>
      </div>
    </div>
    <div class="audit-aging-backdrop" id="audit-deck-backdrop" style="display:none" aria-hidden="true"></div>
    <div class="audit-aging-panel audit-deck-modal-panel" id="audit-deck-modal" role="dialog" aria-modal="true" aria-labelledby="audit-deck-modal-title" aria-hidden="true" style="display:none">
      <div class="audit-aging-inner">
        <div class="audit-deck-upload-layer" id="audit-deck-upload-layer" aria-hidden="true">
          <p class="audit-deck-upload-layer-kicker">Step 1 — Upload</p>
          <h4 class="audit-deck-upload-layer-title" id="audit-deck-upload-layer-title"></h4>
          <p class="audit-deck-upload-layer-hint" id="audit-deck-upload-layer-hint"></p>
          <button type="button" class="nav-btn audit-deck-upload-layer-browse" id="audit-deck-upload-layer-browse"></button>
        </div>
        <div class="audit-deck-dashboard-exit" id="audit-deck-dashboard-exit" role="toolbar" aria-hidden="true">
          <button type="button" class="nav-btn audit-deck-dashboard-btn" id="audit-deck-dashboard-btn"></button>
        </div>
        <div class="audit-aging-head">
          <h3 class="audit-aging-title" id="audit-deck-modal-title"></h3>
          <button type="button" class="audit-aging-close" id="audit-deck-modal-close" aria-label="{html.escape(tr(loc, "audit_obs_detail_close"))}">×</button>
        </div>
        <div class="audit-deck-modal-toolbar">
          <div class="audit-deck-modal-toolbar-main">
            <p class="muted audit-deck-modal-hint" id="audit-deck-modal-hint"></p>
            <span class="audit-deck-filename audit-deck-modal-filename" id="audit-deck-filename" style="display:none"></span>
          </div>
          <div class="audit-deck-modal-actions">
            <label class="audit-deck-fullpage-lbl" for="audit-deck-fullpage-cb">
              <input type="checkbox" id="audit-deck-fullpage-cb" aria-labelledby="audit-deck-fullpage-lbl-text" />
              <span id="audit-deck-fullpage-lbl-text"></span>
            </label>
            <button type="button" class="nav-btn" id="audit-deck-browse-btn"></button>
            <input type="file" id="audit-deck-file" accept=".pptx,.ppt,.pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.ms-powerpoint,application/pdf" style="display:none" aria-hidden="true" />
            <button type="button" class="nav-btn" id="audit-deck-download-btn" style="display:none"></button>
          </div>
        </div>
        <div class="audit-aging-body audit-deck-modal-body">
          <p class="audit-deck-modal-viewer-heading" id="audit-deck-viewer-title"></p>
          <div class="audit-deck-viewer-inner audit-deck-modal-viewer" id="audit-deck-viewer-inner">
            <iframe id="audit-deck-pdf-frame" title="" style="display:none"></iframe>
            <div id="audit-deck-pptx-host" class="audit-deck-pptx-host" style="display:none"></div>
            <p class="muted" id="audit-deck-empty-hint"></p>
          </div>
        </div>
      </div>
    </div>
    <div class="audit-deck-missing-backdrop" id="audit-deck-missing-backdrop" style="display:none" aria-hidden="true"></div>
    <div class="audit-deck-missing-panel" id="audit-deck-missing-panel" role="alertdialog" aria-modal="true" aria-labelledby="audit-deck-missing-title" aria-describedby="audit-deck-missing-msg" aria-hidden="true" tabindex="-1" style="display:none">
      <div class="audit-deck-missing-inner">
        <div class="audit-deck-missing-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="9.5" y1="12.5" x2="14.5" y2="17.5"/>
            <line x1="14.5" y1="12.5" x2="9.5" y2="17.5"/>
          </svg>
        </div>
        <p class="audit-deck-missing-report" id="audit-deck-missing-report"></p>
        <h3 class="audit-deck-missing-title" id="audit-deck-missing-title"></h3>
        <p class="audit-deck-missing-msg" id="audit-deck-missing-msg"></p>
        <button type="button" class="nav-btn audit-deck-missing-ok" id="audit-deck-missing-ok"></button>
      </div>
    </div>
  </main>
  <script>
    const payload = {json.dumps(chart_payload, ensure_ascii=False)};
    try {{
      if (window.parent && window.parent !== window) {{
        document.body.classList.add("multi-shell-embedded");
      }}
    }} catch (_mse) {{}}
    const U = payload.ui || {{}};
    const chartDefaults = {{
      color: '#334155',
      borderColor: 'rgba(15, 23, 42, 0.18)',
      font: {{ family: (U.fontFamily || "Outfit, system-ui, sans-serif"), size: 13 }}
    }};
    Chart.defaults.color = chartDefaults.color;
    Chart.defaults.borderColor = chartDefaults.borderColor;
    Chart.defaults.font = chartDefaults.font;
    function chartPctStr(v, total) {{
      if (!total) return "0%";
      return (Math.round((v / total) * 1000) / 10) + "%";
    }}
    function chartTooltipBarPercentOfTotal(ctx) {{
      const ds = ctx.dataset;
      const v = Number(ctx.parsed.y) || 0;
      let sum = 0;
      for (let i = 0; i < ds.data.length; i++) sum += Number(ds.data[i]) || 0;
      return (ds.label ? ds.label + ": " : "") + v + " (" + chartPctStr(v, sum) + ")";
    }}
    function chartTooltipBarGroupPercent(ctx) {{
      const chart = ctx.chart;
      const di = ctx.dataIndex;
      let g = 0;
      for (let i = 0; i < chart.data.datasets.length; i++) {{
        g += Number(chart.data.datasets[i].data[di]) || 0;
      }}
      const v = Number(ctx.parsed.y) || 0;
      return (ctx.dataset.label ? ctx.dataset.label + ": " : "") + v + " (" + chartPctStr(v, g) + ")";
    }}
    function chartTooltipLineSeriesPercent(ctx) {{
      const ds = ctx.dataset;
      let sum = 0;
      for (let i = 0; i < ds.data.length; i++) sum += Number(ds.data[i]) || 0;
      const v = ctx.parsed.y != null ? Number(ctx.parsed.y) : Number(ctx.parsed);
      return (ds.label ? ds.label + ": " : "") + v + " (" + chartPctStr(v, sum) + ")";
    }}
    function chartTooltipStackSharePercent(ctx) {{
      const chart = ctx.chart;
      const di = ctx.dataIndex;
      let g = 0;
      for (let i = 0; i < chart.data.datasets.length; i++) {{
        g += Number(chart.data.datasets[i].data[di]) || 0;
      }}
      const v = Number(ctx.raw) || 0;
      return (ctx.dataset.label ? ctx.dataset.label + ": " : "") + v + " (" + chartPctStr(v, g) + ")";
    }}
    (function registerDashboardPercentPlugin() {{
      if (typeof Chart === "undefined") return;
      Chart.register({{
        id: "dashboardPercentOnChart",
        afterDatasetsDraw: function (chart) {{
          const t = chart.config.type;
          const ctx = chart.ctx;
          const data = chart.data;
          if (!data.datasets || !data.datasets.length) return;
          const fontFam = (Chart.defaults.font && Chart.defaults.font.family) || "system-ui,sans-serif";

          if (t === "pie" || t === "doughnut") {{
            const ds = data.datasets[0];
            const vals = ds.data.map(function (x) {{ return Number(x) || 0; }});
            const total = vals.reduce(function (a, b) {{ return a + b; }}, 0);
            if (!total) return;
            const meta = chart.getDatasetMeta(0);
            meta.data.forEach(function (arc, i) {{
              const v = vals[i];
              const ang = arc.endAngle - arc.startAngle;
              if (ang < 0.12 || v / total < 0.03) return;
              const p = arc.tooltipPosition();
              const txt = chartPctStr(v, total);
              ctx.save();
              ctx.font = "600 13px " + fontFam;
              ctx.textAlign = "center";
              ctx.textBaseline = "middle";
              ctx.lineWidth = 3;
              ctx.strokeStyle = "rgba(255,255,255,0.95)";
              ctx.fillStyle = "rgba(15,23,42,0.9)";
              ctx.strokeText(txt, p.x, p.y);
              ctx.fillText(txt, p.x, p.y);
              ctx.restore();
            }});
            return;
          }}

          if (t === "bar") {{
            const n = data.labels.length;
            const dsCount = data.datasets.length;
            let grandTotal = 0;
            if (dsCount === 1) {{
              for (let j = 0; j < n; j++) {{
                grandTotal += Number(data.datasets[0].data[j]) || 0;
              }}
            }}
            for (let i = 0; i < n; i++) {{
              let groupSum = 0;
              for (let d = 0; d < dsCount; d++) {{
                groupSum += Number(data.datasets[d].data[i]) || 0;
              }}
              const denom = dsCount === 1 ? grandTotal : groupSum;
              if (!denom) continue;
              for (let d = 0; d < dsCount; d++) {{
                const meta = chart.getDatasetMeta(d);
                if (meta.hidden) continue;
                const bar = meta.data[i];
                if (!bar) continue;
                const v = Number(data.datasets[d].data[i]) || 0;
                const pct = chartPctStr(v, denom);
                const x = bar.x;
                const y = bar.y;
                const base = bar.base;
                const ly = Math.min(y, base) - 6;
                ctx.save();
                ctx.font = "600 12px " + fontFam;
                ctx.textAlign = "center";
                ctx.textBaseline = "bottom";
                ctx.lineWidth = 2;
                ctx.strokeStyle = "rgba(255,255,255,0.92)";
                ctx.fillStyle = "rgba(15,23,42,0.9)";
                ctx.strokeText(pct, x, ly);
                ctx.fillText(pct, x, ly);
                ctx.restore();
              }}
            }}
            return;
          }}

          if (t === "line" && data.datasets.length === 1) {{
            const ds = data.datasets[0];
            const vals = ds.data.map(function (x) {{ return Number(x) || 0; }});
            const total = vals.reduce(function (a, b) {{ return a + b; }}, 0);
            if (!total) return;
            const meta = chart.getDatasetMeta(0);
            meta.data.forEach(function (pt, i) {{
              const p = pt.getProps(["x", "y"], true);
              const pct = chartPctStr(vals[i], total);
              ctx.save();
              ctx.font = "600 11px " + fontFam;
              ctx.textAlign = "center";
              ctx.textBaseline = "bottom";
              ctx.lineWidth = 2;
              ctx.strokeStyle = "rgba(255,255,255,0.9)";
              ctx.fillStyle = "#334155";
              ctx.strokeText(pct, p.x, p.y - 6);
              ctx.fillText(pct, p.x, p.y - 6);
              ctx.restore();
            }});
          }}
        }},
      }});
    }})();
    const T = payload.theme || {{ h1: 265, h2: 190, h3: 320 }};
    const h = (a, s, l, o) => (o != null)
      ? ("hsla(" + a + "," + s + "%," + l + "%," + o + ")")
      : ("hsl(" + a + "," + s + "%," + l + "%)");
    const downloadReportFilename = {download_filename_json};
    function bindSaveReportHtml(controlId) {{
      const el = document.getElementById(controlId);
      if (!el) return;
      const doSave = function () {{
        try {{
          if (typeof window.__aiExcelFlushUserEditsForExport === "function") {{
            window.__aiExcelFlushUserEditsForExport();
          }}
        }} catch (_flush) {{}}
        const docHtml = "<!DOCTYPE html>\\n" + document.documentElement.outerHTML;
        const blob = new Blob([docHtml], {{ type: "text/html;charset=utf-8" }});
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = downloadReportFilename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(a.href);
      }};
      if (el.tagName === "INPUT" && el.type === "checkbox") {{
        el.addEventListener("change", function () {{
          if (!el.checked) return;
          doSave();
          el.checked = false;
        }});
      }} else {{
        el.addEventListener("click", doSave);
      }}
    }}
    bindSaveReportHtml("save-report-html-cb");
    bindSaveReportHtml("save-report-html-cb-audit");
    const FF = payload.file_filters || {{}};
    let chartSegment = null;
    let chartTrend = null;

    function mountStaticSegmentTrend() {{
      const segmentRows = payload.segment || [];
      const trendRows = payload.trend || [];
      if (segmentRows.length) {{
        const k = Object.keys(segmentRows[0]).find(x => x !== "segment") || Object.keys(segmentRows[0])[1];
        const canvas = document.getElementById("segmentChart");
        new Chart(canvas, {{
          type: "bar",
          data: {{
            labels: segmentRows.map(r => r.segment),
            datasets: [{{
              label: k,
              data: segmentRows.map(r => r[k]),
              backgroundColor: (ctx) => {{
                const chart = ctx.chart;
                const {{ ctx: cctx, chartArea }} = chart;
                if (!chartArea) return h(T.h1, 74, 44, 0.88);
                const g = cctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top);
                g.addColorStop(0, h(T.h2, 72, 40, 0.68));
                g.addColorStop(1, h(T.h1, 76, 38, 0.92));
                return g;
              }},
              borderRadius: 8,
              borderSkipped: false
            }}]
          }},
          options: {{
            maintainAspectRatio: false,
            plugins: {{
              legend: {{ display: false }},
              tooltip: {{ callbacks: {{ label: chartTooltipBarPercentOfTotal }} }},
            }},
            scales: {{
              x: {{ grid: {{ display: false }}, ticks: {{ maxRotation: 45 }} }},
              y: {{ beginAtZero: true, grid: {{ color: 'rgba(15,23,42,0.08)' }} }}
            }}
          }}
        }});
      }}
      if (trendRows.length) {{
        const tk = Object.keys(trendRows[0])[0];
        const vk = Object.keys(trendRows[0])[1];
        new Chart(document.getElementById("trendChart"), {{
          type: "line",
          data: {{
            labels: trendRows.map(r => r[tk]),
            datasets: [{{
              label: vk,
              data: trendRows.map(r => r[vk]),
              borderColor: h(T.h2, 78, 48),
              backgroundColor: h(T.h2, 74, 38, 0.16),
              fill: true,
              tension: 0.35,
              pointRadius: 5,
              pointBackgroundColor: h(T.h1, 70, 48),
              pointBorderColor: "#fff",
              pointBorderWidth: 2
            }}]
          }},
          options: {{
            maintainAspectRatio: false,
            plugins: {{
              legend: {{ labels: {{ color: '#334155' }} }},
              tooltip: {{ callbacks: {{ label: chartTooltipLineSeriesPercent }} }},
            }},
            scales: {{
              x: {{ grid: {{ color: 'rgba(15,23,42,0.06)' }} }},
              y: {{ grid: {{ color: 'rgba(15,23,42,0.1)' }}, beginAtZero: true }}
            }}
          }}
        }});
      }}
    }}

    function ffCellKey(v) {{
      if (v === true || v === false) return v ? "true" : "false";
      if (v == null) return "";
      if (typeof v === "number" && Number.isFinite(v)) {{
        if (Number.isInteger(v)) return String(v);
        const t = Math.trunc(v);
        if (v === t) return String(t);
        return String(v);
      }}
      return String(v).trim();
    }}
    function ffCellKeyNormString(s) {{
      if (s == null) return "";
      return String(s).replace(/\\u00a0/g, " ").trim();
    }}
    function auditToolbarDimMatch(dimKey, cellVal, filterVal) {{
      const rv0 = ffCellKey(cellVal);
      const fv0 = ffCellKey(filterVal);
      if (rv0 === fv0) return true;
      if (dimKey !== "co" && dimKey !== "sco") return false;
      if (rv0 === "" || fv0 === "") return false;
      return ffCellKeyNormString(rv0).toLowerCase() === ffCellKeyNormString(fv0).toLowerCase();
    }}
    function aoRowIsUsable(r) {{
      if (!r) return false;
      const y = ffCellKey(r.y);
      const o = ffCellKey(r.obs);
      return y !== "" || o !== "";
    }}

    (function mountAuditObservation() {{
      const AO = payload.audit_observation;
      if (AO && Array.isArray(AO.rows)) {{
        AO.rows = AO.rows.filter(aoRowIsUsable);
      }}
      function snapshotReviewsForExport() {{
        let reviewsSnap = "";
        try {{
          const ta = document.getElementById("audit-reviews-textarea");
          if (ta) {{
            const v = ta.value;
            reviewsSnap = String(v != null ? v : "");
            while (ta.firstChild) ta.removeChild(ta.firstChild);
            if (v) ta.appendChild(document.createTextNode(v));
          }}
        }} catch (_e) {{}}
        return reviewsSnap;
      }}
      function writeAuditPersistScript(planRows, planCellBg, reviewsSnap) {{
        try {{
          let prev = document.getElementById("audit-dashboard-user-persist");
          while (prev) {{
            prev.parentNode.removeChild(prev);
            prev = document.getElementById("audit-dashboard-user-persist");
          }}
          const s = document.createElement("script");
          s.id = "audit-dashboard-user-persist";
          s.type = "application/json";
          const persistObj = {{
            v: 1,
            planRows: planRows || [],
            planCellBg: planCellBg || [],
            reviewsNote: String(reviewsSnap != null ? reviewsSnap : ""),
          }};
          s.textContent = JSON.stringify(persistObj).replace(/</g, "\\u003c");
          if (document.body.firstChild) document.body.insertBefore(s, document.body.firstChild);
          else document.body.appendChild(s);
        }} catch (_e) {{}}
      }}
      function persistAuditUserEdits() {{
        try {{ capturePlanDraftRows(); }} catch (_e0) {{}}
        try {{
          writeAuditPersistScript(planDraftRows || [], planCellBgHex || [], snapshotReviewsForExport());
        }} catch (_e1) {{}}
      }}
      const defGrid = document.getElementById("default-stat-grid");
      const topBar = document.getElementById("audit-top-bar");
      if (!AO || !AO.available) {{
        if (topBar) topBar.style.display = "none";
        const pieSecOff = document.getElementById("audit-pie-section");
        if (pieSecOff) pieSecOff.style.display = "none";
        const brandAsideOff = document.getElementById("brand-context-aside");
        if (brandAsideOff) brandAsideOff.classList.remove("brand-context-aside--visible");
        const brandCoHostOff = document.getElementById("brand-company-filter-host");
        if (brandCoHostOff) {{
          brandCoHostOff.innerHTML = "";
          brandCoHostOff.classList.remove("brand-company-filter-host--visible");
          brandCoHostOff.classList.remove("brand-company-filter-host--hidden");
          brandCoHostOff.classList.remove("brand-company-filter-host--compact");
        }}
        window.__aiExcelFlushUserEditsForExport = function () {{
          writeAuditPersistScript([], [], snapshotReviewsForExport());
        }};
        window.__aiExcelResetAuditChoices = function () {{}};
        return;
      }}
      if (defGrid) defGrid.style.display = "none";
      if (topBar) topBar.style.display = "block";
      const pieSectionEl = document.getElementById("audit-pie-section");
      if (pieSectionEl) pieSectionEl.style.display = "block";
      const ui = AO.ui || {{}};
      const pieTia = document.getElementById("audit-pie-title-ia");
      const pieTyr = document.getElementById("audit-pie-title-year");
      const pieTrt = document.getElementById("audit-pie-title-rating");
      const pieTot = document.getElementById("audit-pie-title-obs");
      if (pieTia) pieTia.textContent = ui.auditPieIaTitle || "";
      if (pieTyr) pieTyr.textContent = ui.auditPieYearTitle || "";
      if (pieTrt) pieTrt.textContent = ui.auditPieRatingTitle || "";
      if (pieTot) pieTot.textContent = ui.auditPieObsTitle || "";
      if (topBar && ui.topBarAria) topBar.setAttribute("aria-label", ui.topBarAria);
      const truncEl = document.getElementById("audit-truncated-note");
      if (truncEl && AO.truncated && ui.truncatedHint) {{
        truncEl.style.display = "block";
        truncEl.textContent = ui.truncatedHint;
      }}
      const detailBackdrop = document.getElementById("audit-obs-detail-backdrop");
      const detailPanel = document.getElementById("audit-obs-detail-panel");
      const detailClose = document.getElementById("audit-obs-detail-close");
      const detailTitle = document.getElementById("audit-obs-detail-title");
      const detailSum = document.getElementById("audit-obs-detail-v-sum");
      const detailRec = document.getElementById("audit-obs-detail-v-rec");
      const detailChipDue = document.getElementById("audit-obs-detail-chip-due");
      const detailChipRt = document.getElementById("audit-obs-detail-chip-rt");
      const detailKDue = document.getElementById("audit-obs-detail-k-due");
      const detailKRt = document.getElementById("audit-obs-detail-k-rt");
      const detailVDue = document.getElementById("audit-obs-detail-v-due");
      const detailVRt = document.getElementById("audit-obs-detail-v-rt");
      const detailEmailWrap = document.getElementById("audit-obs-detail-email-wrap");
      const detailSendEmailBtn = document.getElementById("audit-obs-detail-send-email");
      const detailEmailStatus = document.getElementById("audit-obs-detail-email-status");
      (function ensureAuditObsDetailDownloadPpt() {{
        try {{
          const wrap = detailEmailWrap;
          if (!wrap || document.getElementById("audit-obs-detail-download-ppt")) return;
          const dl = document.createElement("button");
          dl.type = "button";
          dl.className = "audit-obs-detail-email-btn";
          dl.id = "audit-obs-detail-download-ppt";
          const st = document.createElement("span");
          st.className = "audit-obs-detail-email-status";
          st.id = "audit-obs-detail-download-status";
          st.setAttribute("aria-live", "polite");
          wrap.appendChild(dl);
          wrap.appendChild(st);
        }} catch (_eEns) {{}}
      }})();
      const detailDownloadPptBtn = document.getElementById("audit-obs-detail-download-ppt");
      const detailDownloadStatus = document.getElementById("audit-obs-detail-download-status");
      let detailRowForEmail = null;
      const agingCb = document.getElementById("audit-aging-matrix-cb");
      const agingLbl = document.getElementById("audit-aging-matrix-label");
      const agingRevisedCb = document.getElementById("audit-aging-revised-cb");
      const agingRevisedLbl = document.getElementById("audit-aging-revised-label");
      const agingBackdrop = document.getElementById("audit-aging-backdrop");
      const agingPanel = document.getElementById("audit-aging-panel");
      const agingClose = document.getElementById("audit-aging-close");
      const agingTitle = document.getElementById("audit-aging-title");
      const agingHintEl = document.getElementById("audit-aging-hint");
      const agingHeadRow = document.getElementById("audit-aging-head-row");
      const agingBodyRows = document.getElementById("audit-aging-body-rows");
      const planCb = document.getElementById("audit-plan-status-cb");
      const planLbl = document.getElementById("audit-plan-status-label");
      const reviewsCb = document.getElementById("audit-reviews-cb");
      const additionalNotesCb = document.getElementById("audit-additional-notes-cb");
      const additionalNotesLbl = document.getElementById("audit-additional-notes-label");
      const reviewsLbl = document.getElementById("audit-reviews-label");
      const reviewsBackdrop = document.getElementById("audit-reviews-backdrop");
      const reviewsPanel = document.getElementById("audit-reviews-panel");
      const reviewsClose = document.getElementById("audit-reviews-close");
      const reviewsTitle = document.getElementById("audit-reviews-title");
      const reviewsDownloadBtn = document.getElementById("audit-reviews-download");
      const reviewsTextarea = document.getElementById("audit-reviews-textarea");
      const planBackdrop = document.getElementById("audit-plan-backdrop");
      const planPanel = document.getElementById("audit-plan-panel");
      const planClose = document.getElementById("audit-plan-close");
      const planTitle = document.getElementById("audit-plan-title");
      const planHeadRow = document.getElementById("audit-plan-head-row");
      const planBodyRows = document.getElementById("audit-plan-body-rows");
      const planDownloadPptBtn = document.getElementById("audit-plan-download-ppt");
      const planAddRowBtn = document.getElementById("audit-plan-add-row");
      const planUploadBtn = document.getElementById("audit-plan-upload-btn");
      const planUploadFile = document.getElementById("audit-plan-upload-file");
      const planColortoolsLabel = document.getElementById("audit-plan-colortools-label");
      const planCellHintEl = document.getElementById("audit-plan-cell-hint");
      const planCellFillLbl = document.getElementById("audit-plan-cell-fill-lbl");
      const planPaletteCb = document.getElementById("audit-plan-palette-cb");
      const planPaletteBody = document.getElementById("audit-plan-palette-body");
      const planPaletteToggleLbl = document.getElementById("audit-plan-palette-toggle-lbl");
      const planThemeColorsLbl = document.getElementById("audit-plan-theme-colors-lbl");
      const planStandardColorsLbl = document.getElementById("audit-plan-standard-colors-lbl");
      const planThemeSwatches = document.getElementById("audit-plan-theme-swatches");
      const planStandardSwatches = document.getElementById("audit-plan-standard-swatches");
      const planMoreColorsBtn = document.getElementById("audit-plan-more-colors-btn");
      const planCellColorInput = document.getElementById("audit-plan-cell-color");
      const planCellApplyBtn = document.getElementById("audit-plan-cell-apply");
      const planColResetBtn = document.getElementById("audit-plan-col-reset");
      const planClearAllCb = document.getElementById("audit-plan-clear-all-cb");
      const planClearAllLabel = document.getElementById("audit-plan-clear-all-label");
      const planClearAllWrap = document.getElementById("audit-plan-clear-all-wrap");
      const deckAttachCb = document.getElementById("audit-deck-attach-cb");
      const deckAttachLbl = document.getElementById("audit-deck-attach-label");
      const highRiskCb = document.getElementById("audit-high-risk-cb");
      const highRiskLbl = document.getElementById("audit-high-risk-label");
      const tgaViolationsCb = document.getElementById("audit-tga-violations-cb");
      const tgaViolationsLbl = document.getElementById("audit-tga-violations-label");
      const missingVehicleCb = document.getElementById("audit-missing-vehicle-cb");
      const missingVehicleLbl = document.getElementById("audit-missing-vehicle-label");
      const internalAuditQuarterlyCb = document.getElementById("audit-internal-audit-quarterly-cb");
      const internalAuditQuarterlyLbl = document.getElementById("audit-internal-audit-quarterly-label");
      const specialAssignmentCb = document.getElementById("audit-special-assignment-cb");
      const specialAssignmentLbl = document.getElementById("audit-special-assignment-label");
      const deckUploadLayer = document.getElementById("audit-deck-upload-layer");
      const deckUploadLayerTitle = document.getElementById("audit-deck-upload-layer-title");
      const deckUploadLayerHint = document.getElementById("audit-deck-upload-layer-hint");
      const deckUploadLayerBrowse = document.getElementById("audit-deck-upload-layer-browse");
      let deckPanelMode = "committee";
      const deckFilesByMode = {{ committee: null, highRisk: null, tgaViolations: null, missingVehicle: null, internalAuditQuarterly: null, specialAssignment: null }};
      const deckAttachToggles = [deckAttachCb, highRiskCb, tgaViolationsCb, missingVehicleCb, internalAuditQuarterlyCb, specialAssignmentCb];
      const deckBackdrop = document.getElementById("audit-deck-backdrop");
      const deckModal = document.getElementById("audit-deck-modal");
      const deckModalClose = document.getElementById("audit-deck-modal-close");
      const deckModalTitle = document.getElementById("audit-deck-modal-title");
      const deckModalHint = document.getElementById("audit-deck-modal-hint");
      const deckFullPageCb = document.getElementById("audit-deck-fullpage-cb");
      const deckFullPageLblText = document.getElementById("audit-deck-fullpage-lbl-text");
      const deckBrowseBtn = document.getElementById("audit-deck-browse-btn");
      const deckFileInput = document.getElementById("audit-deck-file");
      const deckDownloadBtn = document.getElementById("audit-deck-download-btn");
      const deckFilename = document.getElementById("audit-deck-filename");
      const deckViewerTitle = document.getElementById("audit-deck-viewer-title");
      const deckViewerInner = document.getElementById("audit-deck-viewer-inner");
      const deckPdfFrame = document.getElementById("audit-deck-pdf-frame");
      const deckPptxHost = document.getElementById("audit-deck-pptx-host");
      const deckEmptyHint = document.getElementById("audit-deck-empty-hint");
      const deckDashboardBtn = document.getElementById("audit-deck-dashboard-btn");
      const deckDashboardExit = document.getElementById("audit-deck-dashboard-exit");
      let deckBlobUrls = [];
      let deckLastFile = null;
      let embeddedDeckLoadSig = null;
      const embeddedAltDeckLoadSig = {{ highRisk: null, tgaViolations: null, missingVehicle: null, internalAuditQuarterly: null, specialAssignment: null }};
      let deckLastObjectUrl = null;
      let deckPptxViewer = null;
      let deckPptxSvgViewer = null;
      let deckPptxResizeObs = null;
      let deckPptxAspectRatio = null;
      let deckPptxLoadGeneration = 0;
      let deckCanvasResizeTimer = null;
      let deckPdfPage = 1;
      const emptyMark = ui.obsDetailEmpty || "—";
      let agingMatrixUseRevised = false;
      const hasStandardAgingDates = AO.has_implementation_due === true;
      const hasRevisedDateCol = AO.has_revised_date === true;
      const hasAgingDateSource = !!(hasStandardAgingDates || hasRevisedDateCol);
      const showDetailAgingChip = hasStandardAgingDates;
      if (detailKDue) detailKDue.textContent = ui.obsAgingDaysLabel || "Aging";
      if (detailKRt) detailKRt.textContent = ui.obsDetailRating || "";
      if (!showDetailAgingChip && detailChipDue && detailChipRt) {{
        detailChipDue.style.display = "none";
        detailChipRt.style.gridColumn = "1 / -1";
      }}
      if (detailSendEmailBtn && AO.has_email) {{
        detailSendEmailBtn.textContent = ui.obsEmailSend || "Send email";
      }}
      if (detailDownloadPptBtn) {{
        const dlbl = ui.obsDetailDownloadPpt || ui.planDownloadPpt || "Download as PowerPoint";
        detailDownloadPptBtn.textContent = dlbl;
        detailDownloadPptBtn.setAttribute("aria-label", dlbl);
      }}
      function fmtObsDetailCell(v) {{
        if (v == null || v === "") return emptyMark;
        return String(v);
      }}
      function fmtDetailDate(v) {{
        if (v == null || v === "") return emptyMark;
        if (typeof v === "number" && Number.isFinite(v)) {{
          const dn = new Date(v);
          if (!isNaN(dn.getTime())) {{
            try {{
              return dn.toLocaleDateString(undefined, {{ year: "numeric", month: "short", day: "numeric" }});
            }} catch (e1) {{ return String(v); }}
          }}
          return String(v);
        }}
        const s = String(v).trim();
        const d2 = new Date(s);
        if (!isNaN(d2.getTime()) && s.length >= 4) {{
          try {{
            return d2.toLocaleDateString(undefined, {{ year: "numeric", month: "short", day: "numeric" }});
          }} catch (e2) {{ return s; }}
        }}
        return s;
      }}
      function formatObsDetailRating(row) {{
        if (!AO.has_rating) return emptyMark;
        const rv = ffCellKey(row.rt);
        if (rv === "") return emptyMark;
        const rtypes = AO.rating_types || [];
        for (let ri = 0; ri < rtypes.length; ri++) {{
          if (String(rtypes[ri].value).toLowerCase() === rv.toLowerCase()) return rtypes[ri].label;
        }}
        return rv;
      }}
      function obsDateCellRaw(v) {{
        if (v == null) return null;
        const s = String(v).trim();
        return s === "" ? null : v;
      }}
      function rowAgingDateRaw(row) {{
        const t = obsDateCellRaw(row.tdate);
        if (t != null) return t;
        return obsDateCellRaw(row.idue);
      }}
      function rowAgingMatrixDueDateRaw(row) {{
        return obsDateCellRaw(row.idue);
      }}
      function rowRevisedMatrixDateRaw(row) {{
        return obsDateCellRaw(row.rdate);
      }}
      function rowMatrixCompareDateRaw(row) {{
        if (agingMatrixUseRevised && hasRevisedDateCol) {{
          return rowRevisedMatrixDateRaw(row);
        }}
        return rowAgingMatrixDueDateRaw(row);
      }}
      function detailAgingDaysText(row) {{
        if (!showDetailAgingChip) return emptyMark;
        const due = parseObsDate(rowMatrixCompareDateRaw(row));
        if (!due) return emptyMark;
        let refDate = null;
        if (revisedDateVal) refDate = parseObsDate(revisedDateVal);
        if (!refDate) {{
          const now = new Date();
          refDate = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
        }}
        const dueDay = Math.floor(due.getTime() / 86400000);
        const refDay = Math.floor(refDate.getTime() / 86400000);
        const days = refDay - dueDay;
        return String(days) + " " + (ui.obsAgingDaysSuffix || "days");
      }}
      function closeAuditObsDetail() {{
        detailRowForEmail = null;
        if (detailDownloadPptBtn) detailDownloadPptBtn.disabled = false;
        if (detailDownloadStatus) detailDownloadStatus.textContent = "";
        if (detailEmailStatus) detailEmailStatus.textContent = "";
        if (detailBackdrop) {{
          detailBackdrop.classList.remove("audit-obs-detail-backdrop--open");
          detailBackdrop.style.display = "none";
          detailBackdrop.setAttribute("aria-hidden", "true");
        }}
        if (detailPanel) {{
          detailPanel.classList.remove("audit-obs-detail-panel--open");
          detailPanel.style.display = "none";
          detailPanel.setAttribute("aria-hidden", "true");
        }}
        document.body.style.overflow = "";
      }}
      function openAuditObsDetail(row) {{
        if (!detailPanel || !detailTitle) return;
        const name = row.obs == null ? "" : String(row.obs);
        detailTitle.textContent = name || emptyMark;
        const ds = fmtObsDetailCell(row.osum);
        const dr = fmtObsDetailCell(row.rec);
        if (showDetailAgingChip && detailChipDue && detailVDue) {{
          detailChipDue.style.display = "";
          const agingStr = detailAgingDaysText(row);
          detailVDue.textContent = agingStr;
          detailVDue.classList.toggle("audit-detail-chip-v--muted", agingStr === emptyMark);
        }}
        if (detailVRt) {{
          const rtStr = formatObsDetailRating(row);
          detailVRt.textContent = rtStr;
          detailVRt.classList.toggle("audit-detail-chip-v--muted", rtStr === emptyMark);
        }}
        detailRowForEmail = row;
        if (detailEmailWrap) detailEmailWrap.hidden = false;
        if (detailDownloadStatus) detailDownloadStatus.textContent = "";
        if (detailSendEmailBtn) {{
          detailSendEmailBtn.hidden = !AO.has_email;
          if (detailEmailStatus) detailEmailStatus.hidden = !AO.has_email;
          if (AO.has_email) {{
            const em = row.em != null ? String(row.em).trim() : "";
            detailSendEmailBtn.disabled = !em;
            detailSendEmailBtn.title = em ? "" : (ui.obsEmailMissing || "");
            if (detailEmailStatus) detailEmailStatus.textContent = "";
          }} else {{
            detailSendEmailBtn.disabled = true;
            detailSendEmailBtn.title = "";
            if (detailEmailStatus) detailEmailStatus.textContent = "";
          }}
        }}
        if (detailSum) {{
          detailSum.textContent = ds;
          detailSum.classList.toggle("audit-detail-v--muted", ds === emptyMark);
        }}
        if (detailRec) {{
          detailRec.textContent = dr;
          detailRec.classList.toggle("audit-detail-v--muted", dr === emptyMark);
        }}
        if (detailBackdrop) {{
          detailBackdrop.style.display = "block";
          detailBackdrop.classList.add("audit-obs-detail-backdrop--open");
          detailBackdrop.setAttribute("aria-hidden", "false");
        }}
        detailPanel.style.display = "flex";
        detailPanel.classList.add("audit-obs-detail-panel--open");
        detailPanel.setAttribute("aria-hidden", "false");
        document.body.style.overflow = "hidden";
        const detailBodyEl = document.querySelector("#audit-obs-detail-panel .audit-obs-detail-body");
        if (detailBodyEl) detailBodyEl.scrollTop = 0;
        if (detailClose) detailClose.focus();
      }}
      const AUDIT_ADD_NOTES_ORDER_LS = "auditAdditionalNotesOrder";
      function obsNotesPickHas(id) {{
        const n = Number(id);
        if (!Number.isFinite(n)) return false;
        return obsNotesPickedOrder.indexOf(n) >= 0;
      }}
      function saveObsNotesOrderLs() {{
        try {{ localStorage.setItem(AUDIT_ADD_NOTES_ORDER_LS, JSON.stringify(obsNotesPickedOrder)); }} catch (_so1) {{}}
      }}
      function loadObsNotesOrderLs() {{
        try {{
          const raw = localStorage.getItem(AUDIT_ADD_NOTES_ORDER_LS);
          if (!raw) return;
          const arr = JSON.parse(raw);
          if (!Array.isArray(arr)) return;
          obsNotesPickedOrder = arr.map(function (x) {{ return parseInt(x, 10); }}).filter(function (x) {{ return Number.isFinite(x); }});
        }} catch (_so2) {{ obsNotesPickedOrder = []; }}
      }}
      function syncAdditionalNotesInlinePanel() {{
        const p = document.getElementById("audit-additional-notes-inline-panel");
        if (!p || !additionalNotesCb) return;
        p.style.display = additionalNotesCb.checked ? "block" : "none";
        renderAdditionalNotesStack();
      }}
      function renderAdditionalNotesStack() {{
        const ol = document.getElementById("audit-additional-notes-ol");
        const emptyEl = document.getElementById("audit-additional-notes-empty");
        if (!ol) return;
        ol.innerHTML = "";
        const rowsSrc = Array.isArray(AO.rows) ? AO.rows : [];
        for (let ni = 0; ni < obsNotesPickedOrder.length; ni++) {{
          const id = obsNotesPickedOrder[ni];
          const row = rowsSrc.find(function (r) {{ return r != null && r._idx === id; }});
          const li = document.createElement("li");
          li.className = "audit-additional-notes-li";
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "audit-additional-notes-item-btn";
          const title = !row
            ? ("#" + String(id))
            : ((row.obs == null || String(row.obs).trim() === "") ? emptyMark : String(row.obs));
          const num = document.createElement("span");
          num.className = "audit-additional-notes-item-num";
          num.textContent = String(ni + 1) + ". ";
          const main = document.createElement("span");
          main.className = "audit-additional-notes-item-title";
          main.textContent = title;
          btn.appendChild(num);
          btn.appendChild(main);
          if (row) {{
            btn.setAttribute("aria-label", (ui.obsDetailOpenHint || "View") + ": " + title);
            btn.addEventListener("click", function (ev) {{
              ev.preventDefault();
              openAuditObsDetail(row);
            }});
          }} else {{
            btn.disabled = true;
            btn.title = ui.additionalNotesRowMissingHint || "";
          }}
          li.appendChild(btn);
          ol.appendChild(li);
        }}
        if (emptyEl) {{
          emptyEl.textContent = ui.additionalNotesEmptyHint || "";
          emptyEl.style.display = obsNotesPickedOrder.length ? "none" : "block";
        }}
      }}
      function updateObsNotesPickMeta() {{
        const n = obsNotesPickedOrder.length;
        if (obsNotesPickMetaEl) {{
          const tpl = String(ui.obsNotesAddedCountTpl || "{{n}}");
          obsNotesPickMetaEl.textContent = tpl.replace(/\\{{n\\}}/g, String(n));
        }}
        if (obsNotesClearPicksBtn) obsNotesClearPicksBtn.disabled = n === 0;
      }}
      function clearAllObsNotesPicks() {{
        obsNotesPickedOrder.length = 0;
        saveObsNotesOrderLs();
        updateObsNotesPickMeta();
        renderAdditionalNotesStack();
      }}
      function appendObsRowToAdditionalNotes(row) {{
        const idn = Number(row._idx);
        if (row._idx == null || !Number.isFinite(idn)) return;
        if (obsNotesPickHas(idn)) return;
        obsNotesPickedOrder.push(idn);
        saveObsNotesOrderLs();
        updateObsNotesPickMeta();
        renderAdditionalNotesStack();
        try {{ aoRefresh(); }} catch (_aonR) {{}}
      }}
      if (detailSendEmailBtn && AO.has_email) {{
        detailSendEmailBtn.addEventListener("click", async function () {{
          const row = detailRowForEmail;
          if (!row) return;
          const to = row.em != null ? String(row.em).trim() : "";
          const obsName = row.obs == null ? "" : String(row.obs);
          if (!to) {{
            if (detailEmailStatus) detailEmailStatus.textContent = ui.obsEmailMissing || "";
            return;
          }}
          const subj = "ملاحظة تدقيق: " + obsName;
          const bodyAr = "السلام عليكم،\\n\\nنود إبلاغكم بخصوص الملاحظة التالية:\\n" + obsName + "\\n\\nمع التحية،";
          function openMailtoFallback() {{
            const mailto = "mailto:" + encodeURIComponent(to) + "?subject=" + encodeURIComponent(subj) + "&body=" + encodeURIComponent(bodyAr);
            try {{ window.location.href = mailto; }} catch (_le) {{ window.open(mailto, "_blank"); }}
            if (detailEmailStatus) detailEmailStatus.textContent = ui.obsEmailMailtoHint || "";
          }}
          let api = null;
          let apiFallbacks = [];
          try {{
            api = window.__AI_EXCEL_MAIL_API__ || null;
            if (!api && window.parent && window.parent !== window) {{
              api = window.parent.__AI_EXCEL_MAIL_API__ || null;
            }}
            const fb0 = window.__AI_EXCEL_MAIL_API_FALLBACKS__;
            const fb1 = (!fb0 && window.parent && window.parent !== window) ? window.parent.__AI_EXCEL_MAIL_API_FALLBACKS__ : fb0;
            if (Array.isArray(fb1)) apiFallbacks = fb1.slice();
          }} catch (_api0) {{ api = null; apiFallbacks = []; }}
          if (detailEmailStatus) detailEmailStatus.textContent = ui.obsEmailSending || "";
          if (api || (apiFallbacks && apiFallbacks.length)) {{
            try {{
              const targets = [];
              if (api) targets.push(api);
              for (let i = 0; i < apiFallbacks.length; i++) {{
                const u = String(apiFallbacks[i] || "").trim();
                if (!u) continue;
                if (targets.indexOf(u) === -1) targets.push(u);
              }}
              let data = {{}};
              let sent = false;
              let lastErr = "";
              let sawSmtpNotConfigured = false;
              for (let ti = 0; ti < targets.length; ti++) {{
                const target = targets[ti];
                try {{
                  const res = await fetch(target, {{
                    method: "POST",
                    headers: {{ "Content-Type": "application/json" }},
                    body: JSON.stringify({{ to: to, observation: obsName }}),
                  }});
                  data = {{}};
                  try {{ data = await res.json(); }} catch (_je) {{}}
                  if (res.ok && data.ok) {{
                    sent = true;
                    break;
                  }}
                  lastErr = data && data.error ? String(data.error) : ("HTTP " + String(res.status || ""));
                  if (lastErr === "smtp_not_configured") {{
                    sawSmtpNotConfigured = true;
                    break;
                  }}
                }} catch (eReq) {{
                  lastErr = eReq && eReq.message ? String(eReq.message) : "network_error";
                }}
              }}
              if (sent) {{
                if (detailEmailStatus) detailEmailStatus.textContent = ui.obsEmailOk || "";
              }} else if (sawSmtpNotConfigured) {{
                const msg = (ui.obsEmailSmtpNeeded || ui.obsEmailFail || "");
                if (detailEmailStatus) detailEmailStatus.textContent = msg;
              }} else {{
                const err = lastErr;
                const lowErr = String(err || "").toLowerCase();
                if (lowErr.indexOf("failed to fetch") !== -1 || lowErr.indexOf("network_error") !== -1) {{
                  openMailtoFallback();
                  return;
                }}
                let msg = ui.obsEmailFail || "";
                if (err === "smtp_not_configured") msg = (ui.obsEmailSmtpNeeded || msg);
                if (detailEmailStatus) detailEmailStatus.textContent = msg + (err && err !== "smtp_not_configured" ? (": " + err) : "");
              }}
            }} catch (_fe) {{
              openMailtoFallback();
            }}
          }} else {{
            openMailtoFallback();
          }}
        }});
      }}
      function safeObsPptxBase(s) {{
        let t = String(s || "").trim().slice(0, 72);
        if (!t) t = "observation";
        const badChars = ["<", ">", ":", String.fromCharCode(34), "/", String.fromCharCode(92), "|", "?", "*"];
        for (let bi = 0; bi < badChars.length; bi++) {{
          const ch = badChars[bi];
          t = t.split(ch).join("_");
        }}
        while (t.indexOf("  ") >= 0) t = t.split("  ").join(" ");
        t = t.trim();
        return t || "observation";
      }}
      function finishObsPptxExport(statusMsg) {{
        if (detailDownloadPptBtn) detailDownloadPptBtn.disabled = false;
        if (detailDownloadStatus) detailDownloadStatus.textContent = statusMsg || "";
      }}
      if (detailDownloadPptBtn) {{
        detailDownloadPptBtn.addEventListener("click", function () {{
          const row = detailRowForEmail;
          if (!row) return;
          if (typeof PptxGenJS === "undefined") {{
            const msg = ui.obsDetailDownloadPptMissingLib || ui.obsDetailDownloadPptFail || "";
            finishObsPptxExport(msg);
            try {{ window.alert(msg); }} catch (_adpA) {{}}
            return;
          }}
          detailDownloadPptBtn.disabled = true;
          if (detailDownloadStatus) detailDownloadStatus.textContent = ui.obsDetailDownloadPptBusy || "";
          try {{
            const pptx = new PptxGenJS();
            pptx.layout = "LAYOUT_WIDE";
            const x0 = 0.4;
            const wTxt = 12.5;
            const yBottom = 7.28;
            const name = row.obs == null ? "" : String(row.obs);
            const titleTxt = name.trim() ? name : emptyMark;
            const metaBits = [];
            if (showDetailAgingChip) {{
              const ag = detailAgingDaysText(row);
              if (ag !== emptyMark) metaBits.push(String(ui.obsAgingDaysLabel || "Aging") + ": " + ag);
            }}
            if (AO.has_rating) {{
              const rt = formatObsDetailRating(row);
              if (rt !== emptyMark) metaBits.push(String(ui.obsDetailRating || "") + ": " + rt);
            }}
            const sumLbl = ui.obsDetailSummaryLbl || "Summary";
            const sumBody = fmtObsDetailCell(row.osum);
            const recLbl = ui.obsDetailRecLbl || "Recommendation";
            const recBody = fmtObsDetailCell(row.rec);
            const sumFont = sumBody.length > 3500 ? 9 : sumBody.length > 1800 ? 10 : 11;
            const recFont = recBody.length > 3500 ? 9 : recBody.length > 1800 ? 10 : 11;

            const slide1 = pptx.addSlide();
            slide1.background = {{ color: "F8FAFC" }};
            slide1.addText(titleTxt, {{
              x: x0, y: 0.18, w: wTxt, h: 0.72,
              fontFace: "Arial", bold: true, fontSize: 18, color: "0F172A", valign: "top", wrap: true
            }});
            let yAfterTitle = 0.95;
            if (metaBits.length) {{
              slide1.addText(metaBits.join("   ·   "), {{
                x: x0, y: yAfterTitle, w: wTxt, h: 0.38,
                fontFace: "Arial", fontSize: 11, color: "64748B", valign: "top", wrap: true
              }});
              yAfterTitle = 1.38;
            }}
            slide1.addText(sumLbl, {{
              x: x0, y: yAfterTitle, w: 4.2, h: 0.26,
              fontFace: "Arial", bold: true, fontSize: 12, color: "334155", valign: "top"
            }});
            const ySumBody = yAfterTitle + 0.3;
            const hSumBody = Math.max(1.2, yBottom - ySumBody - 0.12);
            slide1.addText(sumBody, {{
              x: x0, y: ySumBody, w: wTxt, h: hSumBody,
              fontFace: "Arial", fontSize: sumFont, color: "1E293B", valign: "top", wrap: true
            }});

            const slide2 = pptx.addSlide();
            slide2.background = {{ color: "F8FAFC" }};
            slide2.addText(titleTxt, {{
              x: x0, y: 0.18, w: wTxt, h: 0.52,
              fontFace: "Arial", bold: true, fontSize: 13, color: "475569", valign: "top", wrap: true
            }});
            slide2.addText(recLbl, {{
              x: x0, y: 0.78, w: 4.2, h: 0.26,
              fontFace: "Arial", bold: true, fontSize: 12, color: "334155", valign: "top"
            }});
            const yRecBody = 1.08;
            const hRecBody = Math.max(1.2, yBottom - yRecBody - 0.12);
            slide2.addText(recBody, {{
              x: x0, y: yRecBody, w: wTxt, h: hRecBody,
              fontFace: "Arial", fontSize: recFont, color: "1E293B", valign: "top", wrap: true
            }});
            const stamp = new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-");
            const fileName = safeObsPptxBase(name) + "-" + stamp + ".pptx";
            const w = pptx.writeFile({{ fileName: fileName }});
            if (w && typeof w.then === "function") {{
              w.then(function () {{
                finishObsPptxExport(ui.obsDetailDownloadPptOk || "");
              }}).catch(function () {{
                const msg = ui.obsDetailDownloadPptFail || "";
                finishObsPptxExport(msg);
                try {{ window.alert(msg); }} catch (_adpB) {{}}
              }});
            }} else {{
              finishObsPptxExport(ui.obsDetailDownloadPptOk || "");
            }}
          }} catch (_adpErr) {{
            const msg = ui.obsDetailDownloadPptFail || "";
            finishObsPptxExport(msg);
            try {{ window.alert(msg); }} catch (_adpC) {{}}
          }}
        }});
      }}
      if (detailClose) detailClose.addEventListener("click", closeAuditObsDetail);
      if (detailBackdrop) detailBackdrop.addEventListener("click", closeAuditObsDetail);
      document.addEventListener("keydown", function (ev) {{
        if (ev.key !== "Escape") return;
        if (detailPanel && detailPanel.style.display !== "none") {{
          closeAuditObsDetail();
          return;
        }}
        if (agingPanel && agingPanel.style.display !== "none") {{
          closeAgingMatrix();
          return;
        }}
        if (planPanel && planPanel.style.display !== "none") {{
          closePlanStatus();
          return;
        }}
        if (deckModal && deckModal.style.display !== "none") {{
          try {{ ev.preventDefault(); }} catch (_pe) {{}}
          if (typeof deckCloseModalAndReset === "function") deckCloseModalAndReset();
          return;
        }}
      }});
      const brandCoHost = document.getElementById("brand-company-filter-host");
      const isEmbeddedMultiShell = document.body.classList.contains("multi-shell-embedded");
      let tb = document.getElementById("audit-filter-toolbar");
      if (!tb) {{
        tb = document.createElement("div");
        tb.id = "audit-filter-toolbar";
        tb.setAttribute("aria-hidden", "true");
        tb.style.cssText = "position:absolute;width:0;height:0;overflow:hidden;clip:rect(0,0,0,0);";
        try {{ document.body.appendChild(tb); }} catch (_tb0) {{}}
      }}
      let dims = Array.isArray(AO.filter_dims) ? AO.filter_dims.slice() : [];
      function dimIsSubcompany(dim) {{
        const k = String(dim && dim.key != null ? dim.key : "").toLowerCase();
        const l = String(dim && dim.label != null ? dim.label : "").toLowerCase();
        return (
          k === "sco" ||
          k === "subcompany" ||
          l.indexOf("subcompany") !== -1 ||
          l.indexOf("sub company") !== -1 ||
          l.indexOf("sub-company") !== -1 ||
          l.indexOf("sub_company") !== -1 ||
          l.indexOf("الشركة التابعة") !== -1
        );
      }}
      function dimIsCompany(dim) {{
        if (dimIsSubcompany(dim)) return false;
        const k = String(dim && dim.key != null ? dim.key : "").toLowerCase();
        const l = String(dim && dim.label != null ? dim.label : "").toLowerCase();
        if (l.indexOf("sub") !== -1 && l.indexOf("company") !== -1) return false;
        return k === "co" || k === "company" || l.indexOf("company") !== -1 || l.indexOf("الشركة") !== -1;
      }}
      const rawCompanyIdx = dims.findIndex(dimIsCompany);
      let rawSubcompanyIdx = dims.findIndex(dimIsSubcompany);
      if (rawSubcompanyIdx < 0) {{
        const rowsForSub = Array.isArray(AO.rows) ? AO.rows : [];
        const subVals = Array.from(
          new Set(
            rowsForSub
              .map(function (r) {{ return String((r && r.sco) != null ? r.sco : "").trim(); }})
              .filter(function (v) {{ return v !== ""; }})
          )
        );
        if (subVals.length > 0) {{
          subVals.sort(function (a, b) {{ return String(a).localeCompare(String(b)); }});
          dims.push({{
            key: "sco",
            label: ui.subcompanyLabel || "Subcompany",
            values: subVals
          }});
          rawSubcompanyIdx = dims.length - 1;
        }}
      }}
      const companyIdx = isEmbeddedMultiShell ? -1 : rawCompanyIdx;
      // Keep Subcompany filter available even in multi-file embedded shell.
      const subcompanyIdx = rawSubcompanyIdx;
      const hasCompanyFilterDim = companyIdx >= 0;
      const hasSubcompanyFilterDim = subcompanyIdx >= 0;
      const hasBrandFilters = hasCompanyFilterDim || hasSubcompanyFilterDim;
      const brandBoxSubcompanyOnly =
        hasCompanyFilterDim && hasSubcompanyFilterDim && companyIdx >= 0 && subcompanyIdx >= 0;
      if (hasBrandFilters) {{
        if (brandCoHost) {{
          brandCoHost.classList.add("brand-company-filter-host--visible");
          brandCoHost.classList.remove("brand-company-filter-host--hidden");
        }}
        const brandAsideOn = document.getElementById("brand-context-aside");
        if (brandAsideOn) {{
          brandAsideOn.classList.add("brand-context-aside--visible");
          if (hasSubcompanyFilterDim) brandAsideOn.classList.add("brand-context-aside--sc-only");
          else brandAsideOn.classList.remove("brand-context-aside--sc-only");
        }}
      }} else {{
        if (brandCoHost) {{
          brandCoHost.innerHTML = "";
          brandCoHost.classList.remove("brand-company-filter-host--visible");
          brandCoHost.classList.remove("brand-company-filter-host--hidden");
          brandCoHost.classList.remove("brand-company-filter-host--compact");
          brandCoHost.classList.remove("brand-company-filter-host--sc-only");
        }}
        const brandAsideNoCo = document.getElementById("brand-context-aside");
        if (brandAsideNoCo) {{
          brandAsideNoCo.classList.remove("brand-context-aside--visible");
          brandAsideNoCo.classList.remove("brand-context-aside--sc-only");
        }}
      }}
      const ALL = AO.all_token;
      const tilesHost = document.getElementById("audit-ia-tiles");
      const openList = document.getElementById("audit-open-list");
      const openEmpty = document.getElementById("audit-open-empty");
      const obsHeading = document.getElementById("audit-obs-heading");
      const ratingsBox = document.getElementById("audit-box-ratings");
      const ratingBtnHost = document.getElementById("audit-rating-btns");
      if (obsHeading) obsHeading.textContent = ui.obsChecklistIntro || "";

      let activeIaLabels = new Set();
      let brandCompanyFilterReopen = false;
      let activeAuditYears = new Set();
      let activeRatingValues = new Set();
      let activeObsTypeLabels = new Set();
      let obsCheckedIds = null;
      let obsNotesPickedOrder = [];
      let obsTypeStripInited = false;
      let obsTypeStripOrder = null;
      let obsTypeOrderResolved = null;
      const yearBtnHost = document.getElementById("audit-year-btns");
      const yearBox = document.getElementById("audit-box-years");
      const obsTypeBtnHost = document.getElementById("audit-obs-type-btns");
      const obsBarTitle = document.getElementById("audit-obs-bar-title");
      const obsBarMeta = document.getElementById("audit-obs-bar-meta");
      const obsShowListCb = document.getElementById("audit-obs-show-list-cb");
      const obsNamesPanelEl = document.getElementById("audit-obs-names-panel");
      const obsAndFiltersRow = document.getElementById("audit-obs-and-filters-row");
      if (obsShowListCb && ui.obsShowNamesCheckboxAria) obsShowListCb.setAttribute("aria-label", ui.obsShowNamesCheckboxAria);
      const obsCheckTools = document.getElementById("audit-obs-check-tools");
      const obsSelectAllBtn = document.getElementById("audit-obs-select-all");
      const obsSelectNoneBtn = document.getElementById("audit-obs-select-none");
      const obsNotesPickMetaEl = document.getElementById("audit-obs-notes-pick-meta");
      const obsNotesClearPicksBtn = document.getElementById("audit-obs-notes-clear-picks");
      const revisedDateWrap = document.getElementById("audit-obs-revised-date-wrap");
      const revisedDateLabel = document.getElementById("audit-obs-revised-date-label");
      const revisedDateInput = document.getElementById("audit-obs-revised-date");
      let obsNamesPanelExpanded = false;
      let lastObsMetaBase = "";
      let lastObsChecklistN = 0;
      let revisedDateVal = null;
      let lastAgingRows = [];
      let planDraftRows = [];
      let lastPlanRows = [];
      let planCellBgHex = [];
      let planSelectedCell = null;
      const planThemePaletteHex = [
        "#FFFFFF", "#000000", "#E7E6E6", "#44546A", "#5B9BD5", "#ED7D31", "#A5A5A5", "#FFC000", "#4472C4", "#70AD47",
        "#F2F2F2", "#7F7F7F", "#D0CECE", "#D6DCE4", "#DDEBF7", "#FCE4D6", "#EDEDED", "#FFF2CC", "#D9E1F2", "#E2EFDA",
        "#D9D9D9", "#595959", "#AEAAAA", "#ACB9CA", "#BDD7EE", "#F8CBAD", "#DBDBDB", "#FFE699", "#B4C6E7", "#C6E0B4",
        "#BFBFBF", "#3F3F3F", "#7F7F7F", "#8497B0", "#9DC3E6", "#F4B183", "#C9C9C9", "#FFD966", "#8EA9DB", "#A9D18E",
        "#A6A6A6", "#262626", "#595959", "#2F3B4F", "#2E75B6", "#C55A11", "#7F7F7F", "#BF8F00", "#2F5597", "#548235"
      ];
      const planStandardPaletteHex = [
        "#C00000", "#FF0000", "#FFC000", "#FFFF00", "#92D050", "#00B050", "#00B0F0", "#0070C0", "#002060", "#7030A0"
      ];
      function hydratePersistedUserEdits() {{
        const el = document.getElementById("audit-dashboard-user-persist");
        if (!el || !el.textContent || !String(el.textContent).trim()) return;
        try {{
          const o = JSON.parse(el.textContent);
          if (!o || o.v !== 1) return;
          if (Array.isArray(o.planRows) && o.planRows.length) {{
            planDraftRows = o.planRows.map(function (r) {{
              const row = Array.isArray(r) ? r.slice(0, 7) : [];
              while (row.length < 7) row.push("");
              return row.map(function (c) {{ return String(c != null ? c : ""); }});
            }});
          }}
          if (Array.isArray(o.planCellBg) && o.planCellBg.length) {{
            planCellBgHex = o.planCellBg.map(function (r) {{
              const row = Array.isArray(r) ? r.slice(0, 7) : [];
              while (row.length < 7) row.push("#ffffff");
              return row.map(function (c) {{
                const s = String(c != null ? c : "#ffffff").trim();
                return /^#[0-9a-fA-F]{{6}}$/.test(s) ? s : "#ffffff";
              }});
            }});
          }}
          if (typeof o.reviewsNote === "string" && reviewsTextarea) {{
            reviewsTextarea.value = o.reviewsNote;
            try {{ localStorage.setItem("auditOtherReviewsNote", o.reviewsNote); }} catch (_lsH) {{}}
          }}
        }} catch (_e) {{}}
      }}
      hydratePersistedUserEdits();

      function parseObsDateFromEpoch(value) {{
        if (!Number.isFinite(value)) return null;
        let ms = null;
        if (value >= 1e12) ms = value;
        else if (value >= 1e9) ms = value * 1000;
        else return null;
        const dNum = new Date(ms);
        if (isNaN(dNum.getTime())) return null;
        return new Date(Date.UTC(dNum.getUTCFullYear(), dNum.getUTCMonth(), dNum.getUTCDate()));
      }}
      function parseObsDateFromExcelSerial(excelDays) {{
        if (!Number.isFinite(excelDays)) return null;
        const days = Math.floor(excelDays);
        if (days < 1000 || days > 80000) return null;
        const msUtc = (days - 25569) * 86400 * 1000;
        const dNum = new Date(msUtc);
        if (isNaN(dNum.getTime())) return null;
        return new Date(Date.UTC(dNum.getUTCFullYear(), dNum.getUTCMonth(), dNum.getUTCDate()));
      }}
      function parseObsDate(value) {{
        if (value == null || value === "") return null;
        if (typeof value === "number" && Number.isFinite(value)) {{
          const fromEpoch = parseObsDateFromEpoch(value);
          if (fromEpoch) return fromEpoch;
          return parseObsDateFromExcelSerial(value);
        }}
        const s = String(value).trim();
        const serialM = s.match(/^(\\d+(?:\\.\\d+)?)$/);
        if (serialM) {{
          const n = Number(serialM[1]);
          const fromEpoch = parseObsDateFromEpoch(n);
          if (fromEpoch) return fromEpoch;
          const fromSerial = parseObsDateFromExcelSerial(n);
          if (fromSerial) return fromSerial;
        }}
        const iso = s.match(/^(\\d{{4}})-(\\d{{2}})-(\\d{{2}})/);
        if (iso) {{
          const y = Number(iso[1]);
          const mm = Number(iso[2]);
          const dd = Number(iso[3]);
          if (Number.isFinite(y) && Number.isFinite(mm) && Number.isFinite(dd)) {{
            return new Date(Date.UTC(y, mm - 1, dd));
          }}
        }}
        const dmy = s.match(/^(\\d{{1,2}})[\\/\\-](\\d{{1,2}})[\\/\\-](\\d{{4}})$/);
        if (dmy) {{
          const p1 = Number(dmy[1]);
          const p2 = Number(dmy[2]);
          const y = Number(dmy[3]);
          let dd = p1;
          let mm = p2;
          if (p1 > 12 && p2 <= 12) {{ dd = p1; mm = p2; }}
          else if (p2 > 12 && p1 <= 12) {{ dd = p2; mm = p1; }}
          if (Number.isFinite(y) && mm >= 1 && mm <= 12 && dd >= 1 && dd <= 31) {{
            return new Date(Date.UTC(y, mm - 1, dd));
          }}
        }}
        const d = new Date(s);
        if (isNaN(d.getTime())) return null;
        return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
      }}
      function formatIsoDate(d) {{
        if (!d) return "";
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const day = String(d.getDate()).padStart(2, "0");
        return y + "-" + m + "-" + day;
      }}
      function planAgingDayDiff(implementationDue, agingDateOrRef) {{
        const due = parseObsDate(implementationDue);
        let ref = null;
        if (agingDateOrRef instanceof Date) ref = agingDateOrRef;
        else ref = parseObsDate(agingDateOrRef);
        if (!due || !ref) return null;
        const dueDay = Math.floor(due.getTime() / 86400000);
        const refDay = Math.floor(ref.getTime() / 86400000);
        return refDay - dueDay;
      }}
      function normRatingMatrixToken(v) {{
        let k = normAuditColorKey(v);
        if (k === "meduim") k = "medium";
        return k;
      }}
      function resolveAgingMatrixRatingKey(rawRt) {{
        if (!AO.has_rating || rawRt == null) return "";
        const rtypes = AO.rating_types || [];
        const rv = ffCellKey(rawRt);
        if (rv === "") return "";
        const rvLower = rv.toLowerCase();
        const rawTok = normRatingMatrixToken(rv);
        for (let i = 0; i < rtypes.length; i++) {{
          const def = rtypes[i];
          const dv = String(def.value || "").trim().toLowerCase();
          const dl = String(def.label || "").trim().toLowerCase();
          if (dv === rvLower || (dl && dl === rvLower)) return dv;
          if (rawTok && rawTok === normRatingMatrixToken(def.value)) return dv;
          if (dl && rawTok === normRatingMatrixToken(def.label)) return dv;
        }}
        return "";
      }}
      function formatObsRowRating(row) {{
        if (!AO.has_rating) return emptyMark;
        const rv = ffCellKey(row.rt);
        if (rv === "") return emptyMark;
        const rtypes = AO.rating_types || [];
        for (let i = 0; i < rtypes.length; i++) {{
          if (String(rtypes[i].value).toLowerCase() === rv.toLowerCase()) return rtypes[i].label;
        }}
        return rv;
      }}
      function implementationDueText(row) {{
        if (!showDetailAgingChip) return emptyMark;
        return fmtDetailDate(rowAgingDateRaw(row));
      }}
      function ratingClassKey(v) {{
        const k = normAuditColorKey(v);
        if (k === "critical") return "critical";
        if (k === "high") return "high";
        if (k === "medium" || k === "meduim") return "medium";
        if (k === "low" || k === "very low" || k === "closed") return "low";
        return "total";
      }}
      function rowIaStatusKey(row, bl) {{
        const ik = ffCellKey(row.ia);
        const label = ik === "" ? bl : ik;
        return iaStatusColorKey(label);
      }}
      function computeAgingMatrixRows(rows) {{
        const tfNotDue = ui.agingTfNotDue || "Not Due";
        const tfLt6Months = ui.agingTfLt6Months || "Less than 6 months";
        const tfLtYear = ui.agingTfLtYear || "Less than one year";
        const tfOverYear = ui.agingTfOverYear || "Over one year";
        const frames = [tfNotDue, tfLt6Months, tfLtYear, tfOverYear];
        const ratingDefs = (AO.rating_types || []).map(function (rt) {{
          return {{ key: String(rt.value).toLowerCase(), label: rt.label || rt.value }};
        }});
        const counts = {{}};
        const idSets = {{}};
        const useOid = AO.has_observation_id === true;
        const bl = ui.statusBlank || "(blank)";
        frames.forEach(function (f) {{
          counts[f] = {{}};
          idSets[f] = {{}};
          ratingDefs.forEach(function (rt) {{
            counts[f][rt.key] = 0;
            idSets[f][rt.key] = new Set();
          }});
        }});
        const today = new Date();
        const agingRef = parseObsDate(revisedDateVal) || new Date(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()));
        const refDay = Math.floor(agingRef.getTime() / 86400000);
        rows.forEach(function (r) {{
          const rk = resolveAgingMatrixRatingKey(r.rt);
          if (!rk) return;
          const iaKey = rowIaStatusKey(r, bl);
          let frame = null;
          if (iaKey === "open not due") {{
            frame = tfNotDue;
          }} else if (iaKey === "open due") {{
            const target = parseObsDate(rowMatrixCompareDateRaw(r));
            if (!target) return;
            const targetDay = Math.floor(target.getTime() / 86400000);
            const diffDays = refDay - targetDay;
            if (diffDays < 183) frame = tfLt6Months;
            else if (diffDays < 365) frame = tfLtYear;
            else frame = tfOverYear;
          }} else {{
            return;
          }}
          let idKey = "_idx:" + String(r._idx);
          if (useOid) {{
            const ok = ffCellKey(r.oid);
            if (ok !== "") idKey = "id:" + ok;
          }}
          idSets[frame][rk].add(idKey);
        }});
        frames.forEach(function (f) {{
          ratingDefs.forEach(function (rt) {{
            counts[f][rt.key] = idSets[f][rt.key].size;
          }});
        }});
        return {{ frames: frames, ratingDefs: ratingDefs, counts: counts }};
      }}
      function syncAgingPanelTitle() {{
        if (!agingTitle) return;
        const today = new Date();
        const ref = parseObsDate(revisedDateVal) || new Date(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()));
        let dateStr = "";
        try {{
          dateStr = ref.toLocaleDateString(undefined, {{ year: "numeric", month: "short", day: "numeric" }});
        }} catch (_e1) {{
          dateStr = formatIsoDate(ref);
        }}
        const tpl = ui.agingTitleAsOfTpl || "";
        if (tpl && tpl.indexOf("{{date}}") !== -1) {{
          agingTitle.textContent = tpl.split("{{date}}").join(dateStr);
        }} else {{
          agingTitle.textContent = (ui.agingTitle || "Aging Matrix") + " (" + dateStr + ")";
        }}
        if (agingHintEl) {{
          const hint = agingMatrixUseRevised
            ? (ui.agingMatrixHintRevised || ui.agingMatrixHint || "")
            : (ui.agingMatrixHint || "");
          agingHintEl.textContent = hint;
          agingHintEl.hidden = !hint;
        }}
      }}
      function renderAgingMatrix(rows) {{
        if (!agingHeadRow || !agingBodyRows) return;
        syncAgingPanelTitle();
        const m = computeAgingMatrixRows(rows || []);
        const totalLabel = ui.agingColTotal || "Total";
        const tfLabel = ui.agingColTimeFrame || "Time Frame";
        const trh = document.createElement("tr");
        const thTf = document.createElement("th");
        thTf.textContent = tfLabel;
        trh.appendChild(thTf);
        m.ratingDefs.forEach(function (rt) {{
          const th = document.createElement("th");
          th.textContent = rt.label;
          th.className = "audit-aging-th-" + ratingClassKey(rt.key);
          trh.appendChild(th);
        }});
        const thTot = document.createElement("th");
        thTot.textContent = totalLabel;
        thTot.className = "audit-aging-th-total";
        trh.appendChild(thTot);
        agingHeadRow.innerHTML = "";
        agingHeadRow.appendChild(trh);
        agingBodyRows.innerHTML = "";
        const colTotals = {{}};
        m.ratingDefs.forEach(function (rt) {{ colTotals[rt.key] = 0; }});
        let grand = 0;
        m.frames.forEach(function (f) {{
          const trb = document.createElement("tr");
          const tdf = document.createElement("td");
          tdf.textContent = f;
          trb.appendChild(tdf);
          let rowT = 0;
          m.ratingDefs.forEach(function (rt) {{
            const n = m.counts[f][rt.key] || 0;
            rowT += n;
            colTotals[rt.key] += n;
            const td = document.createElement("td");
            td.textContent = n ? String(n) : "";
            trb.appendChild(td);
          }});
          grand += rowT;
          const tdRowT = document.createElement("td");
          tdRowT.textContent = String(rowT);
          trb.appendChild(tdRowT);
          agingBodyRows.appendChild(trb);
        }});
        const trTot = document.createElement("tr");
        trTot.className = "audit-aging-row-total";
        const tdLbl = document.createElement("td");
        tdLbl.textContent = totalLabel;
        trTot.appendChild(tdLbl);
        m.ratingDefs.forEach(function (rt) {{
          const td = document.createElement("td");
          td.textContent = String(colTotals[rt.key] || 0);
          trTot.appendChild(td);
        }});
        const tdGrand = document.createElement("td");
        tdGrand.textContent = String(grand);
        trTot.appendChild(tdGrand);
        agingBodyRows.appendChild(trTot);
      }}
      function closeAgingMatrix() {{
        if (agingBackdrop) {{
          agingBackdrop.style.display = "none";
          agingBackdrop.setAttribute("aria-hidden", "true");
        }}
        if (agingPanel) {{
          agingPanel.style.display = "none";
          agingPanel.setAttribute("aria-hidden", "true");
        }}
        document.body.style.overflow = "";
        try {{
          if (window.parent && window.parent !== window) {{
            window.parent.postMessage({{ type: "deck-modal-state", open: false }}, "*");
          }}
        }} catch (_amc) {{}}
        if (agingCb) agingCb.checked = false;
        if (agingRevisedCb) agingRevisedCb.checked = false;
        agingMatrixUseRevised = false;
      }}
      function openAgingMatrix(rows) {{
        if (!agingPanel || !agingBackdrop) return;
        renderAgingMatrix(rows || []);
        agingBackdrop.style.display = "block";
        agingBackdrop.setAttribute("aria-hidden", "false");
        agingPanel.style.display = "block";
        agingPanel.setAttribute("aria-hidden", "false");
        document.body.style.overflow = "hidden";
        try {{
          if (window.parent && window.parent !== window) {{
            window.parent.postMessage({{ type: "deck-modal-state", open: true }}, "*");
          }}
        }} catch (_amo) {{}}
        if (agingClose) {{
          try {{ agingClose.focus(); }} catch (_af) {{}}
        }}
      }}
      function capturePlanDraftRows() {{
        if (!planBodyRows) return;
        const trs = Array.from(planBodyRows.querySelectorAll("tr"));
        const out = [];
        trs.forEach(function (tr) {{
          const tds = Array.from(tr.querySelectorAll("td"));
          if (tds.length < 7) return;
          out.push(tds.slice(0, 7).map(function (td) {{ return String(td.textContent || "").trim(); }}));
        }});
        planDraftRows = out;
      }}
      function getPlanDraftRows() {{
        return (planDraftRows && planDraftRows.length) ? planDraftRows : null;
      }}
      window.__aiExcelFlushUserEditsForExport = function () {{
        persistAuditUserEdits();
      }};
      function normalizePlanHeader(h) {{
        return String(h || "")
          .trim()
          .toLowerCase()
          .replace(/[%_\\-]/g, " ")
          .replace(/\\s+/g, " ")
          .trim();
      }}
      function mapPlanRowFromRecord(rec) {{
        const keyMap = {{
          project: ["project name", "project"],
          auditable: ["auditable function", "auditable"],
          resource: ["resource allocated", "resource"],
          status: ["project status", "status"],
          planning: ["planning %", "planning"],
          field: ["field work %", "field work", "fieldwork"],
          reporting: ["reporting %", "reporting"],
        }};
        const normRec = {{}};
        Object.keys(rec || {{}}).forEach(function (k) {{ normRec[normalizePlanHeader(k)] = rec[k]; }});
        function pick(keys) {{
          for (let i = 0; i < keys.length; i++) {{
            const nk = normalizePlanHeader(keys[i]);
            if (Object.prototype.hasOwnProperty.call(normRec, nk)) return normRec[nk];
          }}
          return "";
        }}
        return [
          String(pick(keyMap.project) ?? ""),
          String(pick(keyMap.auditable) ?? ""),
          String(pick(keyMap.resource) ?? ""),
          String(pick(keyMap.status) ?? ""),
          String(pick(keyMap.planning) ?? ""),
          String(pick(keyMap.field) ?? ""),
          String(pick(keyMap.reporting) ?? ""),
        ];
      }}
      function fillPlanFromRecords(records) {{
        if (!Array.isArray(records) || !records.length) return false;
        const rows = records.map(mapPlanRowFromRecord).filter(function (r) {{
          return r.some(function (x) {{ return String(x).trim() !== ""; }});
        }});
        if (!rows.length) return false;
        planDraftRows = rows;
        planCellBgHex = [];
        planSelectedCell = null;
        renderPlanStatusTable();
        persistAuditUserEdits();
        return true;
      }}
      function parsePptxPlanFile(arrayBuffer) {{
        if (typeof JSZip === "undefined") return Promise.resolve([]);
        return JSZip.loadAsync(arrayBuffer)
          .then(function (zip) {{
          const names = Object.keys(zip.files).filter(function (n) {{
            return /^ppt\\/slides\\/slide\\d+\\.xml$/i.test(n);
          }}).sort(function (a, b) {{
            const na = parseInt(String(a).replace(/\\D/g, ""), 10) || 0;
            const nb = parseInt(String(b).replace(/\\D/g, ""), 10) || 0;
            return na - nb;
          }});
          const NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main";
          function cellText(tc) {{
            const texts = tc.getElementsByTagNameNS(NS_A, "t");
            let s = "";
            for (let i = 0; i < texts.length; i++) s += texts[i].textContent || "";
            return String(s).replace(/\\s+/g, " ").trim();
          }}
          function tableToRows(tbl) {{
            const rows = [];
            const trs = tbl.getElementsByTagNameNS(NS_A, "tr");
            for (let r = 0; r < trs.length; r++) {{
              const cells = [];
              const tcs = trs[r].getElementsByTagNameNS(NS_A, "tc");
              for (let c = 0; c < tcs.length; c++) cells.push(cellText(tcs[c]));
              rows.push(cells);
            }}
            return rows;
          }}
          function scoreTable(matrix) {{
            if (!matrix || !matrix.length || matrix[0].length < 4) return -1;
            let score = matrix.length * 10 + matrix[0].length;
            const headerLike = matrix[0].map(function (x) {{ return normalizePlanHeader(x); }}).join(" ");
            if (/project|auditable|planning|field|reporting|resource|status/.test(headerLike)) score += 200;
            return score;
          }}
          function collectTblElements(doc) {{
            const out = [];
            let n = doc.getElementsByTagNameNS(NS_A, "tbl");
            if (n && n.length) {{
              for (let i = 0; i < n.length; i++) out.push(n[i]);
              return out;
            }}
            n = doc.getElementsByTagName("tbl");
            if (n && n.length) {{
              for (let j = 0; j < n.length; j++) {{
                const el = n[j];
                if (el && el.namespaceURI === NS_A) out.push(el);
              }}
            }}
            return out;
          }}
          function slideXmlParseFailed(doc) {{
            if (!doc || !doc.documentElement) return true;
            const root = doc.documentElement;
            const ln = String(root.localName || "").toLowerCase();
            if (ln === "parsererror") return true;
            try {{
              const pe = doc.getElementsByTagNameNS("http://www.w3.org/1999/xhtml", "parsererror");
              if (pe && pe.length) return true;
            }} catch (_p0) {{}}
            try {{
              const pe2 = doc.getElementsByTagName("parsererror");
              if (pe2 && pe2.length) return true;
            }} catch (_p1) {{}}
            return false;
          }}
          return Promise.all(names.map(function (sn) {{
            const file = zip.file(sn);
            return file ? file.async("string") : Promise.resolve("");
          }})).then(function (xmls) {{
            const allTables = [];
            xmls.forEach(function (xml) {{
              if (!xml || !xml.trim()) return;
              let doc = null;
              try {{
                doc = new DOMParser().parseFromString(xml, "application/xml");
              }} catch (_e) {{
                return;
              }}
              if (slideXmlParseFailed(doc)) return;
              const tbls = collectTblElements(doc);
              for (let t = 0; t < tbls.length; t++) {{
                allTables.push(tableToRows(tbls[t]));
              }}
            }});
            let best = null;
            let bestScore = -1;
            allTables.forEach(function (m) {{
              const s = scoreTable(m);
              if (s > bestScore) {{ bestScore = s; best = m; }}
            }});
            if (!best || !best.length) return [];
            let hdrIdx = 0;
            for (let i = 0; i < Math.min(3, best.length); i++) {{
              const joined = best[i].map(function (x) {{ return normalizePlanHeader(x); }}).join(" ");
              if (/project|auditable|planning|field|reporting|resource|status/.test(joined)) {{
                hdrIdx = i;
                break;
              }}
            }}
            const hdr = best[hdrIdx];
            const dataRows = best.slice(hdrIdx + 1);
            return dataRows.map(function (vals) {{
              const rec = {{}};
              hdr.forEach(function (h, j) {{ rec[h] = vals[j] !== undefined ? vals[j] : ""; }});
              return rec;
            }});
          }});
        }})
          .catch(function () {{
            return [];
          }});
      }}
      function appendPlanEmptyRow() {{
        capturePlanDraftRows();
        const blank = ["", "", "", "", "", "", ""];
        if (!planDraftRows || !planDraftRows.length) {{
          planDraftRows = [];
          for (let i = 0; i < 8; i++) planDraftRows.push(blank.slice());
        }} else {{
          planDraftRows = planDraftRows.map(function (r) {{ return r.slice(0, 7); }});
        }}
        planDraftRows.push(blank.slice());
        renderPlanStatusTable();
        persistAuditUserEdits();
      }}
      function planPlanColumnLabels() {{
        return [
          ui.planColProjectName || "Project Name",
          ui.planColAuditableFunction || "Auditable function",
          ui.planColResourceAllocated || "Resource Allocated",
          ui.planColProjectStatus || "Project Status",
          ui.planColPlanningPct || "Planning %",
          ui.planColFieldWorkPct || "Field Work %",
          ui.planColReportingPct || "Reporting %",
        ];
      }}
      function planEmptyColorRow() {{
        return ["#ffffff", "#ffffff", "#ffffff", "#ffffff", "#ffffff", "#ffffff", "#ffffff"];
      }}
      function ensurePlanCellMatrix(nRows) {{
        const emptyRow = planEmptyColorRow;
        if (!planCellBgHex) planCellBgHex = [];
        while (planCellBgHex.length < nRows) planCellBgHex.push(emptyRow());
        while (planCellBgHex.length > nRows) planCellBgHex.pop();
        for (let i = 0; i < planCellBgHex.length; i++) {{
          if (!planCellBgHex[i] || planCellBgHex[i].length < 7) planCellBgHex[i] = emptyRow();
          else planCellBgHex[i] = planCellBgHex[i].slice(0, 7);
        }}
      }}
      function planCellFgForBg(hex) {{
        const m = String(hex || "").match(/^#?([0-9a-f]{{6}})$/i);
        if (!m) return "#111827";
        const n = m[1];
        const r = parseInt(n.slice(0, 2), 16) / 255;
        const g = parseInt(n.slice(2, 4), 16) / 255;
        const b = parseInt(n.slice(4, 6), 16) / 255;
        const L = 0.2126 * r + 0.7152 * g + 0.0722 * b;
        return L > 0.62 ? "#111827" : "#ffffff";
      }}
      function syncPlanCellPickerState() {{
        const picker = planCellColorInput || document.getElementById("audit-plan-cell-color");
        if (!picker) return;
        const swatches = [];
        if (planThemeSwatches) swatches.push.apply(swatches, Array.from(planThemeSwatches.querySelectorAll(".audit-plan-swatch-btn")));
        if (planStandardSwatches) swatches.push.apply(swatches, Array.from(planStandardSwatches.querySelectorAll(".audit-plan-swatch-btn")));
        if (!planSelectedCell && planBodyRows) {{
          const selectedTd = planBodyRows.querySelector("td.audit-plan-cell--selected");
          const activeTd = document.activeElement && document.activeElement.tagName === "TD" ? document.activeElement : null;
          const td = activeTd || selectedTd;
          if (td) {{
            const tr = td.parentElement;
            if (tr) {{
              const r = Array.prototype.indexOf.call(planBodyRows.querySelectorAll("tr"), tr);
              const c = Array.prototype.indexOf.call(tr.querySelectorAll("td"), td);
              if (r >= 0 && c >= 0) planSelectedCell = {{ r: r, c: c }};
            }}
          }}
        }}
        if (!planSelectedCell) {{
          picker.disabled = true;
          if (planMoreColorsBtn) planMoreColorsBtn.disabled = true;
          swatches.forEach(function (btn) {{ btn.disabled = true; }});
          return;
        }}
        picker.disabled = false;
        if (planMoreColorsBtn) planMoreColorsBtn.disabled = false;
        swatches.forEach(function (btn) {{ btn.disabled = false; }});
        const r = planSelectedCell.r;
        const c = planSelectedCell.c;
        const hex = (planCellBgHex[r] && planCellBgHex[r][c]) || "#ffffff";
        picker.value = hex;
        syncPlanPaletteSelection(hex);
      }}
      function syncPlanPaletteSelection(hex) {{
        const normalized = String(hex || "").toUpperCase();
        const rows = [];
        if (planThemeSwatches) rows.push.apply(rows, Array.from(planThemeSwatches.querySelectorAll(".audit-plan-swatch-btn")));
        if (planStandardSwatches) rows.push.apply(rows, Array.from(planStandardSwatches.querySelectorAll(".audit-plan-swatch-btn")));
        rows.forEach(function (btn) {{
          const bHex = String(btn.getAttribute("data-hex") || "").toUpperCase();
          btn.classList.toggle("audit-plan-swatch-btn--active", bHex === normalized);
        }});
      }}
      function syncPlanPaletteBodyVisibility() {{
        if (!planPaletteBody || !planPaletteCb) return;
        planPaletteBody.classList.toggle("audit-plan-palette-body--open", !!planPaletteCb.checked);
      }}
      function applyPlanCellStyles() {{
        const tbl = document.getElementById("audit-plan-table");
        if (!tbl) return;
        const ths = tbl.querySelectorAll("thead th");
        for (let j = 0; j < ths.length; j++) {{
          ths[j].style.background = "#ffffff";
          ths[j].style.color = "var(--text)";
        }}
        const trs = tbl.querySelectorAll("tbody tr");
        for (let r = 0; r < trs.length; r++) {{
          const tds = trs[r].querySelectorAll("td");
          for (let c = 0; c < tds.length && c < 7; c++) {{
            const td = tds[c];
            const bg = (planCellBgHex[r] && planCellBgHex[r][c]) || "#ffffff";
            td.style.setProperty("background-color", bg, "important");
            td.style.setProperty("color", planCellFgForBg(bg), "important");
            td.classList.toggle("audit-plan-cell--selected", !!(planSelectedCell && planSelectedCell.r === r && planSelectedCell.c === c));
          }}
        }}
      }}
      function initPlanCellColorToolsOnce() {{
        const wrap = document.getElementById("audit-plan-cell-fill-wrap");
        if (!wrap) return;
        if (wrap.__planColorInitDone) return;
        wrap.__planColorInitDone = true;
        const picker = planCellColorInput || document.getElementById("audit-plan-cell-color");
        function resolveActivePlanCell() {{
          if (planSelectedCell) return planSelectedCell;
          if (!planBodyRows) return null;
          const selectedTd = planBodyRows.querySelector("td.audit-plan-cell--selected");
          const activeTd = document.activeElement && document.activeElement.tagName === "TD" ? document.activeElement : null;
          const td = activeTd || selectedTd;
          if (!td) return null;
          const tr = td.parentElement;
          if (!tr) return null;
          const r = Array.prototype.indexOf.call(planBodyRows.querySelectorAll("tr"), tr);
          const c = Array.prototype.indexOf.call(tr.querySelectorAll("td"), td);
          if (r < 0 || c < 0) return null;
          planSelectedCell = {{ r: r, c: c }};
          return planSelectedCell;
        }}
        function applyPickedColor() {{
          const cell = resolveActivePlanCell();
          if (!cell || !picker) return;
          const r = cell.r;
          const c = cell.c;
          ensurePlanCellMatrix(Math.max(planCellBgHex.length, r + 1));
          if (!planCellBgHex[r]) planCellBgHex[r] = planEmptyColorRow();
          planCellBgHex[r][c] = picker.value;
          if (planBodyRows) {{
            const tr = planBodyRows.querySelectorAll("tr")[r];
            if (tr) {{
              const td = tr.querySelectorAll("td")[c];
              if (td) {{
                td.style.setProperty("background-color", picker.value, "important");
                td.style.setProperty("color", planCellFgForBg(picker.value), "important");
              }}
            }}
          }}
          applyPlanCellStyles();
          persistAuditUserEdits();
        }}
        if (planCellHintEl) planCellHintEl.textContent = ui.planCellColorsHint || "";
        if (planCellFillLbl) planCellFillLbl.textContent = ui.planCellFillLabel || "Fill";
        if (planPaletteToggleLbl) planPaletteToggleLbl.textContent = ui.planShowColorsLabel || "Show colors";
        if (planPaletteCb) {{
          planPaletteCb.checked = false;
          planPaletteCb.addEventListener("change", syncPlanPaletteBodyVisibility);
        }}
        syncPlanPaletteBodyVisibility();
        if (planThemeColorsLbl) planThemeColorsLbl.textContent = ui.planThemeColorsLabel || "Theme Colors";
        if (planStandardColorsLbl) planStandardColorsLbl.textContent = ui.planStandardColorsLabel || "Standard Colors";
        if (planCellApplyBtn) planCellApplyBtn.textContent = ui.planCellApplyLabel || "Apply";
        function renderPalette(host, colors) {{
          if (!host) return;
          host.innerHTML = "";
          colors.forEach(function (hex) {{
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "audit-plan-swatch-btn";
            btn.style.background = hex;
            btn.setAttribute("data-hex", hex);
            btn.setAttribute("aria-label", hex);
            btn.addEventListener("click", function () {{
              if (!picker || picker.disabled) return;
              picker.value = hex.toLowerCase();
              syncPlanPaletteSelection(hex);
              applyPickedColor();
            }});
            host.appendChild(btn);
          }});
        }}
        renderPalette(planThemeSwatches, planThemePaletteHex);
        renderPalette(planStandardSwatches, planStandardPaletteHex);
        if (picker) {{
          picker.addEventListener("input", applyPickedColor);
          picker.addEventListener("input", function () {{
            syncPlanPaletteSelection(picker.value);
          }});
          picker.addEventListener("change", function () {{
            syncPlanPaletteSelection(picker.value);
            applyPickedColor();
          }});
        }}
        if (planMoreColorsBtn) {{
          planMoreColorsBtn.textContent = ui.planMoreColorsLabel || "More Colors...";
          planMoreColorsBtn.addEventListener("click", function () {{
            if (!picker || picker.disabled) return;
            picker.click();
          }});
        }}
        if (planCellApplyBtn) {{
          planCellApplyBtn.addEventListener("click", function () {{
            applyPickedColor();
          }});
        }}
      }}
      function renderPlanStatusTable() {{
        if (!planHeadRow || !planBodyRows) return;
        const cols = planPlanColumnLabels();
        const trh = document.createElement("tr");
        cols.forEach(function (c, idx) {{
          const th = document.createElement("th");
          th.textContent = c;
          trh.appendChild(th);
        }});
        planHeadRow.innerHTML = "";
        planHeadRow.appendChild(trh);
        const draftRows = getPlanDraftRows() || [];
        const minPlanRows = 8;
        planBodyRows.innerHTML = "";
        const rowCount = Math.max(minPlanRows, draftRows.length || 0);
        ensurePlanCellMatrix(rowCount);
        if (planSelectedCell && planSelectedCell.r >= rowCount) planSelectedCell = null;
        for (let r = 0; r < rowCount; r++) {{
          const rowVals = draftRows[r] || ["", "", "", "", "", "", ""];
          const trb = document.createElement("tr");
          rowVals.forEach(function (v, idx) {{
            const td = document.createElement("td");
            td.textContent = String(v);
            td.setAttribute("contenteditable", "true");
            td.spellcheck = false;
            td.addEventListener("input", persistAuditUserEdits);
            (function (rowIdx, colIdx) {{
              td.addEventListener("click", function () {{
                planSelectedCell = {{ r: rowIdx, c: colIdx }};
                syncPlanCellPickerState();
                applyPlanCellStyles();
              }});
              td.addEventListener("focus", function () {{
                planSelectedCell = {{ r: rowIdx, c: colIdx }};
                syncPlanCellPickerState();
                applyPlanCellStyles();
              }});
            }})(r, idx);
            trb.appendChild(td);
          }});
          planBodyRows.appendChild(trb);
        }}
        applyPlanCellStyles();
        syncPlanCellPickerState();
      }}
      function clearAllPlanTableData() {{
        const minPlanRows = 8;
        const blank = ["", "", "", "", "", "", ""];
        planDraftRows = [];
        for (let i = 0; i < minPlanRows; i++) planDraftRows.push(blank.slice());
        planCellBgHex = [];
        ensurePlanCellMatrix(minPlanRows);
        planSelectedCell = null;
        renderPlanStatusTable();
        try {{
          writeAuditPersistScript(planDraftRows || [], planCellBgHex || [], snapshotReviewsForExport());
        }} catch (_w) {{}}
      }}
      function closePlanStatus() {{
        if (planBackdrop) {{
          planBackdrop.style.display = "none";
          planBackdrop.setAttribute("aria-hidden", "true");
        }}
        if (planPanel) {{
          planPanel.style.display = "none";
          planPanel.setAttribute("aria-hidden", "true");
        }}
        document.body.style.overflow = "";
        try {{
          if (window.parent && window.parent !== window) {{
            window.parent.postMessage({{ type: "deck-modal-state", open: false }}, "*");
          }}
        }} catch (_pmClosePlan) {{}}
        if (planCb) planCb.checked = false;
      }}
      function openPlanStatus() {{
        if (!planPanel || !planBackdrop) return;
        renderPlanStatusTable();
        planBackdrop.style.display = "block";
        planBackdrop.setAttribute("aria-hidden", "false");
        planPanel.style.display = "block";
        planPanel.setAttribute("aria-hidden", "false");
        document.body.style.overflow = "hidden";
        try {{
          if (window.parent && window.parent !== window) {{
            window.parent.postMessage({{ type: "deck-modal-state", open: true }}, "*");
          }}
        }} catch (_pmOpenPlan) {{}}
      }}
      const AUDIT_REVIEWS_LS = "auditOtherReviewsNote";
      function closeOtherReviews() {{
        if (reviewsBackdrop) {{
          reviewsBackdrop.style.display = "none";
          reviewsBackdrop.setAttribute("aria-hidden", "true");
        }}
        if (reviewsPanel) {{
          reviewsPanel.style.display = "none";
          reviewsPanel.setAttribute("aria-hidden", "true");
        }}
        document.body.style.overflow = "";
        try {{
          if (window.parent && window.parent !== window) {{
            window.parent.postMessage({{ type: "deck-modal-state", open: false }}, "*");
          }}
        }} catch (_pmCloseReviews) {{}}
        if (reviewsCb) reviewsCb.checked = false;
      }}
      function openOtherReviews() {{
        if (!reviewsPanel || !reviewsBackdrop) return;
        if (reviewsCb) reviewsCb.checked = true;
        reviewsBackdrop.style.display = "block";
        reviewsBackdrop.setAttribute("aria-hidden", "false");
        reviewsPanel.style.display = "block";
        reviewsPanel.setAttribute("aria-hidden", "false");
        document.body.style.overflow = "hidden";
        try {{
          if (window.parent && window.parent !== window) {{
            window.parent.postMessage({{ type: "deck-modal-state", open: true }}, "*");
          }}
        }} catch (_pmOpenReviews) {{}}
        if (reviewsTextarea) reviewsTextarea.focus();
      }}

      function applyObsBarMeta() {{
        if (!obsBarMeta) return;
        let m = lastObsMetaBase;
        if (lastObsChecklistN > 0 && !obsNamesPanelExpanded) {{
          const cue = ui.obsNamesToggleHint || "";
          if (cue) m = m + " — " + cue;
        }}
        if (obsNamesPanelExpanded && lastObsChecklistN > 0 && openList) {{
          const k = openList.querySelectorAll("input.audit-obs-cb:checked").length;
          const tpl = String(ui.obsChecklistSelected || "{{k}} / {{n}}");
          m = m + " · " + tpl.replace(/\\{{k\\}}/g, String(k)).replace(/\\{{n\\}}/g, String(lastObsChecklistN));
        }}
        obsBarMeta.textContent = m;
      }}

      function syncObsNamesChecklistPanel() {{
        if (!obsShowListCb || !obsNamesPanelEl) return;
        obsShowListCb.checked = obsNamesPanelExpanded;
        obsNamesPanelEl.style.display = obsNamesPanelExpanded ? "flex" : "none";
        document.body.classList.remove("audit-list-fullscreen");
        if (obsAndFiltersRow) obsAndFiltersRow.classList.toggle("audit-list-expanded", !!obsNamesPanelExpanded);
        applyObsBarMeta();
      }}

      if (obsShowListCb) {{
        syncObsNamesChecklistPanel();
        obsShowListCb.addEventListener("change", function () {{
          obsNamesPanelExpanded = obsShowListCb.checked;
          syncObsNamesChecklistPanel();
          if (obsCheckTools) obsCheckTools.style.display = (obsNamesPanelExpanded && lastObsChecklistN > 0) ? "flex" : "none";
        }});
      }}
      if (obsSelectAllBtn) {{
        obsSelectAllBtn.textContent = ui.obsSelectAll || "Select all";
        obsSelectAllBtn.addEventListener("click", function () {{
          obsCheckedIds = null;
          aoRefresh();
        }});
      }}
      if (obsSelectNoneBtn) {{
        obsSelectNoneBtn.textContent = ui.obsSelectNone || "Clear";
        obsSelectNoneBtn.addEventListener("click", function () {{
          obsCheckedIds = new Set();
          aoRefresh();
        }});
      }}
      if (obsNotesClearPicksBtn) {{
        obsNotesClearPicksBtn.textContent = ui.obsNotesClearPicks || "Clear added notes";
        obsNotesClearPicksBtn.addEventListener("click", function () {{
          clearAllObsNotesPicks();
          try {{ aoRefresh(); }} catch (_onClr) {{}}
        }});
        updateObsNotesPickMeta();
      }}
      if (agingLbl) agingLbl.textContent = ui.agingToggleLabel || "Aging";
      if (agingRevisedLbl) agingRevisedLbl.textContent = ui.agingRevisedToggleLabel || "Revised date";
      if (planLbl) planLbl.textContent = ui.planToggleLabel || "Audit plan status";
      if (planTitle) planTitle.textContent = ui.planTitle || "Audit Plan Status";
      if (planDownloadPptBtn) planDownloadPptBtn.textContent = ui.planDownloadPpt || "Download PowerPoint";
      if (planUploadBtn) {{
        planUploadBtn.textContent = ui.planUploadFile || "Upload file";
        if (ui.planUploadFile) planUploadBtn.setAttribute("aria-label", ui.planUploadFile);
      }}
      if (planAddRowBtn) planAddRowBtn.textContent = ui.planAddRow || "Add row";
      if (planClearAllLabel) planClearAllLabel.textContent = ui.planClearAllDataLabel || "Clear all table data";
      if (planClearAllCb && ui.planClearAllDataAria) planClearAllCb.setAttribute("aria-label", ui.planClearAllDataAria);
      if (planClearAllWrap && ui.planClearAllDataAria) planClearAllWrap.setAttribute("title", ui.planClearAllDataAria);
      if (planClearAllCb) {{
        planClearAllCb.addEventListener("change", function () {{
          if (!planClearAllCb.checked) return;
          clearAllPlanTableData();
          planClearAllCb.checked = false;
        }});
      }}
      const brandCoReopenBtn = document.getElementById("brand-company-filter-reopen");
      if (brandCoReopenBtn && !brandCoReopenBtn.getAttribute("data-wired")) {{
        brandCoReopenBtn.setAttribute("data-wired", "1");
        brandCoReopenBtn.textContent = ui.brandChangeCompanies || "Change";
        brandCoReopenBtn.addEventListener("click", function () {{
          brandCompanyFilterReopen = true;
          syncBrandCompanyFilterHostVisibility();
          const co = companyFilterSelectEl();
          const sc = typeof subcompanyFilterSelectEl === "function" ? subcompanyFilterSelectEl() : null;
          const tryFocus = function (el) {{
            if (!el) return false;
            try {{
              el.focus();
              return true;
            }} catch (_fc) {{ return false; }}
          }};
          if (brandBoxSubcompanyOnly) {{
            if (!tryFocus(sc)) tryFocus(co);
          }} else {{
            if (!tryFocus(co)) tryFocus(sc);
          }}
        }});
      }}
      if (planColortoolsLabel) planColortoolsLabel.textContent = ui.planColColorsLabel || "Cell colors";
      if (planColResetBtn) {{
        planColResetBtn.textContent = ui.planColColorsReset || "Reset";
        planColResetBtn.addEventListener("click", function () {{
          let n = 8;
          if (planBodyRows) n = Math.max(8, planBodyRows.querySelectorAll("tr").length);
          else if (planCellBgHex.length) n = planCellBgHex.length;
          planCellBgHex = [];
          ensurePlanCellMatrix(n);
          applyPlanCellStyles();
          syncPlanCellPickerState();
          syncPlanPaletteSelection("#ffffff");
        }});
      }}
      initPlanCellColorToolsOnce();
      if (agingCb) {{
        const agingWrap = agingCb.closest(".audit-obs-aging-toggle");
        if (!hasStandardAgingDates) {{
          agingCb.checked = false;
          if (agingWrap) agingWrap.style.display = "none";
        }} else {{
          if (agingWrap) agingWrap.style.display = "";
          if (agingWrap) {{
            agingWrap.addEventListener("click", function (ev) {{
              if (!ev) return;
              const t = ev.target;
              if (t === agingCb) return;
              ev.preventDefault();
              agingMatrixUseRevised = false;
              agingCb.checked = true;
              if (agingRevisedCb) agingRevisedCb.checked = false;
              openAgingMatrix(lastAgingRows);
            }});
          }}
          agingCb.addEventListener("change", function () {{
            if (agingCb.checked) {{
              agingMatrixUseRevised = false;
              if (agingRevisedCb) agingRevisedCb.checked = false;
              openAgingMatrix(lastAgingRows);
            }} else closeAgingMatrix();
          }});
        }}
      }}
      if (agingRevisedCb) {{
        const arWrap = agingRevisedCb.closest(".audit-obs-aging-toggle");
        if (!hasRevisedDateCol) {{
          agingRevisedCb.checked = false;
          if (arWrap) arWrap.style.display = "none";
        }} else {{
          if (arWrap) arWrap.style.display = "";
          if (arWrap) {{
            arWrap.addEventListener("click", function (ev) {{
              if (!ev) return;
              const t = ev.target;
              if (t === agingRevisedCb) return;
              ev.preventDefault();
              agingMatrixUseRevised = true;
              agingRevisedCb.checked = true;
              if (agingCb) agingCb.checked = false;
              openAgingMatrix(lastAgingRows);
            }});
          }}
          agingRevisedCb.addEventListener("change", function () {{
            if (agingRevisedCb.checked) {{
              agingMatrixUseRevised = true;
              if (agingCb) agingCb.checked = false;
              openAgingMatrix(lastAgingRows);
            }} else closeAgingMatrix();
          }});
        }}
      }}
      if (planCb) {{
        planCb.addEventListener("change", function () {{
          if (planCb.checked) openPlanStatus();
          else closePlanStatus();
        }});
      }}
      if (agingClose) agingClose.addEventListener("click", closeAgingMatrix);
      if (agingBackdrop) agingBackdrop.addEventListener("click", closeAgingMatrix);
      if (planClose) planClose.addEventListener("click", closePlanStatus);
      if (planBackdrop) planBackdrop.addEventListener("click", closePlanStatus);
      if (reviewsLbl) reviewsLbl.textContent = ui.reviewsToggleLabel || "Other audit reviews";
      if (additionalNotesLbl) additionalNotesLbl.textContent = ui.additionalNotesToggleLabel || "ملاحظات اضافية";
      if (reviewsTitle) reviewsTitle.textContent = ui.reviewsTitle || "Other audit reviews";
      if (reviewsDownloadBtn) reviewsDownloadBtn.textContent = ui.reviewsDownload || "Download";
      if (reviewsTextarea) {{
        reviewsTextarea.placeholder = ui.reviewsPlaceholder || "";
        const already = String(reviewsTextarea.value || "").trim() !== "";
        if (!already) {{
          const embeddedNote = String(reviewsTextarea.textContent || "").replace(/\\u00a0/g, " ");
          if (embeddedNote.trim() !== "") {{
            reviewsTextarea.value = embeddedNote;
          }} else {{
            try {{
              const saved = localStorage.getItem(AUDIT_REVIEWS_LS);
              if (saved != null) reviewsTextarea.value = saved;
            }} catch (_ls0) {{}}
          }}
        }}
        reviewsTextarea.addEventListener("input", function () {{
          try {{ localStorage.setItem(AUDIT_REVIEWS_LS, reviewsTextarea.value); }} catch (_ls1) {{}}
          try {{ persistAuditUserEdits(); }} catch (_pe) {{}}
        }});
      }}
      try {{
        loadObsNotesOrderLs();
        updateObsNotesPickMeta();
        renderAdditionalNotesStack();
        if (additionalNotesCb) syncAdditionalNotesInlinePanel();
      }} catch (_anInit) {{}}
      if (reviewsCb) {{
        reviewsCb.addEventListener("change", function () {{
          if (reviewsCb.checked) openOtherReviews();
          else closeOtherReviews();
        }});
      }}
      if (additionalNotesCb) {{
        additionalNotesCb.addEventListener("change", function () {{
          syncAdditionalNotesInlinePanel();
        }});
      }}
      if (reviewsClose) reviewsClose.addEventListener("click", closeOtherReviews);
      if (reviewsBackdrop) reviewsBackdrop.addEventListener("click", closeOtherReviews);
      if (reviewsDownloadBtn) {{
        reviewsDownloadBtn.addEventListener("click", function () {{
          const text = reviewsTextarea ? reviewsTextarea.value : "";
          const blob = new Blob([text], {{ type: "text/plain;charset=utf-8" }});
          const a = document.createElement("a");
          const stamp = new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-");
          a.href = URL.createObjectURL(blob);
          a.download = "other-audit-reviews-" + stamp + ".txt";
          document.body.appendChild(a);
          a.click();
          a.remove();
          URL.revokeObjectURL(a.href);
        }});
      }}
      if (deckAttachLbl) deckAttachLbl.textContent = ui.deckAttachToggleLabel || "تقرير لجنة المراجعة";
      if (highRiskLbl) highRiskLbl.textContent = ui.highRiskToggleLabel || "High Risk Observations & Emerging Risks";
      if (tgaViolationsLbl) tgaViolationsLbl.textContent = ui.tgaViolationsToggleLabel || "TGA Violations Report";
      if (missingVehicleLbl) missingVehicleLbl.textContent = ui.missingVehicleToggleLabel || "Missing Vehicle Report";
      if (internalAuditQuarterlyLbl) internalAuditQuarterlyLbl.textContent = ui.internalAuditQuarterlyToggleLabel || "Internal Audit Quarterly Report";
      if (specialAssignmentLbl) specialAssignmentLbl.textContent = ui.specialAssignmentToggleLabel || "Special Assignment Report";
      if (deckUploadLayerTitle) {{
        deckUploadLayerTitle.textContent = ui.deckUploadTitle || "Upload document";
      }}
      if (deckUploadLayerHint) {{
        deckUploadLayerHint.textContent = ui.deckUploadHint || "";
      }}
      if (deckUploadLayerBrowse) {{
        deckUploadLayerBrowse.textContent = ui.deckBrowse || "Browse…";
      }}
      const DECK_MODE_META = {{
        committee: {{
          title: function () {{ return ui.deckAttachToggleLabel || "Audit committee report"; }},
          hint: function () {{ return ui.deckUploadHint || ""; }},
          uploadTitle: function () {{ return ui.deckUploadTitle || "Upload"; }},
          uploadHint: function () {{ return ui.deckUploadHint || ""; }},
        }},
        highRisk: {{
          title: function () {{ return ui.highRiskToggleLabel || "High Risk Observations & Emerging Risks"; }},
          hint: function () {{ return ui.highRiskUploadHint || ui.deckUploadHint || ""; }},
          uploadTitle: function () {{ return ui.highRiskUploadTitle || ui.deckUploadTitle || "Upload document"; }},
          uploadHint: function () {{ return ui.highRiskUploadHint || ui.deckUploadHint || ""; }},
        }},
        tgaViolations: {{
          title: function () {{ return ui.tgaViolationsToggleLabel || "TGA Violations Report"; }},
          hint: function () {{ return ui.tgaViolationsUploadHint || ui.deckUploadHint || ""; }},
          uploadTitle: function () {{ return ui.tgaViolationsUploadTitle || ui.deckUploadTitle || "Upload document"; }},
          uploadHint: function () {{ return ui.tgaViolationsUploadHint || ui.deckUploadHint || ""; }},
        }},
        missingVehicle: {{
          title: function () {{ return ui.missingVehicleToggleLabel || "Missing Vehicle Report"; }},
          hint: function () {{ return ui.missingVehicleUploadHint || ui.deckUploadHint || ""; }},
          uploadTitle: function () {{ return ui.missingVehicleUploadTitle || ui.deckUploadTitle || "Upload document"; }},
          uploadHint: function () {{ return ui.missingVehicleUploadHint || ui.deckUploadHint || ""; }},
        }},
        internalAuditQuarterly: {{
          title: function () {{ return ui.internalAuditQuarterlyToggleLabel || "Internal Audit Quarterly Report"; }},
          hint: function () {{ return ui.internalAuditQuarterlyUploadHint || ui.deckUploadHint || ""; }},
          uploadTitle: function () {{ return ui.internalAuditQuarterlyUploadTitle || ui.deckUploadTitle || "Upload document"; }},
          uploadHint: function () {{ return ui.internalAuditQuarterlyUploadHint || ui.deckUploadHint || ""; }},
        }},
        specialAssignment: {{
          title: function () {{ return ui.specialAssignmentToggleLabel || "Special Assignment Report"; }},
          hint: function () {{ return ui.specialAssignmentUploadHint || ui.deckUploadHint || ""; }},
          uploadTitle: function () {{ return ui.specialAssignmentUploadTitle || ui.deckUploadTitle || "Upload document"; }},
          uploadHint: function () {{ return ui.specialAssignmentUploadHint || ui.deckUploadHint || ""; }},
        }},
      }};
      function deckIsAltMode(mode) {{
        const m = mode != null ? mode : deckPanelMode;
        return m !== "committee";
      }}
      function deckModeMeta(mode) {{
        return DECK_MODE_META[mode] || DECK_MODE_META.committee;
      }}
      function deckEmbeddedPayloadForMode(mode) {{
        if (mode === "highRisk") return payload.embedded_high_risk_slide_deck;
        if (mode === "tgaViolations") return payload.embedded_tga_violations_slide_deck;
        if (mode === "missingVehicle") return payload.embedded_missing_vehicle_slide_deck;
        if (mode === "internalAuditQuarterly") return payload.embedded_internal_audit_quarterly_slide_deck;
        if (mode === "specialAssignment") return payload.embedded_special_assignment_slide_deck;
        return null;
      }}
      function deckUncheckOtherAttachToggles(activeCb) {{
        for (let i = 0; i < deckAttachToggles.length; i++) {{
          const cb = deckAttachToggles[i];
          if (cb && cb !== activeCb) cb.checked = false;
        }}
      }}
      const deckMissingBackdrop = document.getElementById("audit-deck-missing-backdrop");
      const deckMissingPanel = document.getElementById("audit-deck-missing-panel");
      const deckMissingReport = document.getElementById("audit-deck-missing-report");
      const deckMissingTitle = document.getElementById("audit-deck-missing-title");
      const deckMissingMsg = document.getElementById("audit-deck-missing-msg");
      const deckMissingOk = document.getElementById("audit-deck-missing-ok");
      function deckCloseNoAttachmentNotice() {{
        if (deckMissingBackdrop) {{
          deckMissingBackdrop.style.display = "none";
          deckMissingBackdrop.setAttribute("aria-hidden", "true");
        }}
        if (deckMissingPanel) {{
          deckMissingPanel.style.display = "none";
          deckMissingPanel.setAttribute("aria-hidden", "true");
        }}
      }}
      function deckShowNoAttachmentNotice(mode) {{
        const meta = deckModeMeta(mode || deckPanelMode);
        const reportName = meta.title();
        const title = ui.deckNoAttachmentTitle || "No attachment";
        const msg = ui.deckNoAttachment || "No attachment available for this report.";
        if (deckMissingReport) deckMissingReport.textContent = reportName;
        if (deckMissingTitle) deckMissingTitle.textContent = title;
        if (deckMissingMsg) deckMissingMsg.textContent = msg;
        if (deckMissingOk) deckMissingOk.textContent = ui.deckNoAttachmentOk || "OK";
        if (deckMissingBackdrop) {{
          deckMissingBackdrop.style.display = "block";
          deckMissingBackdrop.setAttribute("aria-hidden", "false");
        }}
        if (deckMissingPanel) {{
          deckMissingPanel.style.display = "block";
          deckMissingPanel.setAttribute("aria-hidden", "false");
          try {{ deckMissingPanel.focus(); }} catch (_mf) {{}}
        }}
      }}
      function deckApplyPanelChrome() {{
        const meta = deckModeMeta(deckPanelMode);
        const title = meta.title();
        const hint = meta.hint();
        if (deckModalTitle) deckModalTitle.textContent = title;
        if (deckModalHint) deckModalHint.textContent = hint;
        if (deckUploadLayerTitle) deckUploadLayerTitle.textContent = meta.uploadTitle();
        if (deckUploadLayerHint) deckUploadLayerHint.textContent = meta.uploadHint();
      }}
      function deckSetUploadFirstMode(on) {{
        if (!deckModal) return;
        if (on) deckModal.classList.add("audit-deck-modal--upload-first");
        else deckModal.classList.remove("audit-deck-modal--upload-first");
        if (deckUploadLayer) deckUploadLayer.setAttribute("aria-hidden", on ? "false" : "true");
      }}
      function deckOpenHighRiskSlideshow() {{
        deckSetUploadFirstMode(false);
        try {{
          if (deckFullPageCb) deckFullPageCb.checked = true;
          deckApplyFullPageMode(true);
        }} catch (_hrSl0) {{}}
        setTimeout(function () {{
          try {{ deckResetViewerToFirstPage(); }} catch (_hrSl1) {{}}
          try {{ deckNotifyDeckLayoutResize(); }} catch (_hrSl2) {{}}
        }}, 120);
        requestAnimationFrame(function () {{
          requestAnimationFrame(function () {{
            try {{ deckNotifyDeckLayoutResize(); }} catch (_hrSl3) {{}}
          }});
        }});
      }}
      function deckFinishAltDeckPresentation() {{
        if (!deckIsAltMode()) return;
        if (!deckModal || deckModal.style.display === "none" || deckModal.getAttribute("aria-hidden") === "true") return;
        deckOpenHighRiskSlideshow();
      }}
      function pickEmbeddedDeckBundleEntry(ed) {{
        if (!ed) return {{ entry: null, sig: null }};
        let entry = null;
        let sig = null;
        if (ed.by_company) {{
          const coSel = typeof companyFilterSelectEl === "function" ? companyFilterSelectEl() : null;
          let picked = [];
          if (coSel && coSel.selectedOptions) {{
            picked = Array.from(coSel.selectedOptions).map(function (o) {{
              return String(o.value != null ? o.value : o.textContent || "").trim();
            }}).filter(function (x) {{ return x !== ""; }});
          }}
          picked.sort(function (a, b) {{ return String(a).localeCompare(String(b)); }});
          if (picked.length === 1 && ed.by_company[picked[0]]) {{
            entry = ed.by_company[picked[0]];
            sig = "co:" + picked[0];
          }} else if (ed.fallback) {{
            entry = ed.fallback;
            sig = "fb";
          }} else {{
            sig = "none";
          }}
        }} else if (ed.data_base64) {{
          entry = ed;
          sig = "legacy";
        }}
        return {{ entry: entry, sig: sig }};
      }}
      function deckEmbeddedBundleHasAttachment(ed) {{
        if (!ed) return false;
        const picked = pickEmbeddedDeckBundleEntry(ed);
        return !!(picked.entry && picked.entry.data_base64);
      }}
      function deckModeHasAttachment(mode) {{
        if (deckFilesByMode[mode]) return true;
        if (mode === "committee") {{
          return deckEmbeddedBundleHasAttachment(payload.embedded_slide_deck);
        }}
        return deckEmbeddedBundleHasAttachment(deckEmbeddedPayloadForMode(mode));
      }}
      function tryOpenDeckAttachMode(mode, cb) {{
        if (!deckModeHasAttachment(mode)) {{
          if (cb) cb.checked = false;
          deckShowNoAttachmentNotice(mode);
          return false;
        }}
        deckUncheckOtherAttachToggles(cb);
        deckPanelMode = mode;
        openDeckModal();
        return true;
      }}
      function loadEmbeddedDeckBundleEntry(entry, defaultName) {{
        if (!entry || !entry.data_base64) return false;
        try {{
          const raw = atob(entry.data_base64);
          const len = raw.length;
          const u8 = new Uint8Array(len);
          for (let i = 0; i < len; i++) u8[i] = raw.charCodeAt(i);
          const mime =
            entry.mime || "application/vnd.openxmlformats-officedocument.presentationml.presentation";
          const blob = new Blob([u8], {{ type: mime }});
          const name = entry.file_name || defaultName || "slides.pptx";
          const f = new File([blob], name, {{ type: mime }});
          void deckHandleFile(f);
          return true;
        }} catch (_ldE) {{
          return false;
        }}
      }}
      function applyEmbeddedDeckForMode(mode) {{
        if (!deckIsAltMode(mode)) return false;
        const ed = deckEmbeddedPayloadForMode(mode);
        if (!ed) return false;
        const picked = pickEmbeddedDeckBundleEntry(ed);
        const entry = picked.entry;
        const sig = picked.sig;
        if (!entry || !entry.data_base64) {{
          if (sig === "none" && ed.by_company) {{
            embeddedAltDeckLoadSig[mode] = sig;
            deckClearViewer();
            deckLastFile = null;
            if (deckFilename) deckFilename.style.display = "none";
            if (deckDownloadBtn) deckDownloadBtn.style.display = "none";
          }}
          return false;
        }}
        if (sig === embeddedAltDeckLoadSig[mode] && deckLastFile) {{
          try {{ deckResetViewerToFirstPage(); }} catch (_hrR0) {{}}
          deckFinishAltDeckPresentation();
          return true;
        }}
        embeddedAltDeckLoadSig[mode] = sig;
        deckClearViewer();
        deckLastFile = null;
        const defaultName =
          mode === "highRisk" ? "high-risk-slides.pptx"
          : mode === "tgaViolations" ? "tga-violations-report.pptx"
          : mode === "missingVehicle" ? "missing-vehicle-report.pptx"
          : mode === "internalAuditQuarterly" ? "internal-audit-quarterly-report.pptx"
          : mode === "specialAssignment" ? "special-assignment-report.pptx"
          : "slides.pptx";
        return loadEmbeddedDeckBundleEntry(entry, defaultName);
      }}
      function rehydrateEmbeddedAltDeckIfNeeded() {{
        if (!deckIsAltMode()) return;
        const cbByMode = {{
          highRisk: highRiskCb,
          tgaViolations: tgaViolationsCb,
          missingVehicle: missingVehicleCb,
          internalAuditQuarterly: internalAuditQuarterlyCb,
          specialAssignment: specialAssignmentCb,
        }};
        const cb = cbByMode[deckPanelMode];
        if (!cb || !cb.checked) return;
        applyEmbeddedDeckForMode(deckPanelMode);
      }}
      function deckPromptUploadIfNeeded() {{
        if (!deckIsAltMode()) return;
        if (applyEmbeddedDeckForMode(deckPanelMode)) return;
        const stored = deckFilesByMode[deckPanelMode];
        if (stored) {{
          deckSetUploadFirstMode(false);
          void deckHandleFile(stored);
          return;
        }}
        deckSetUploadFirstMode(false);
        deckClearViewer();
        if (deckFilename) deckFilename.style.display = "none";
        if (deckDownloadBtn) deckDownloadBtn.style.display = "none";
        deckLastFile = null;
        if (deckEmptyHint) {{
          deckEmptyHint.style.display = "block";
          deckEmptyHint.textContent = ui.deckNoAttachment || "No attachment available for this report.";
        }}
      }}
      deckApplyPanelChrome();
      if (deckFullPageLblText) deckFullPageLblText.textContent = ui.deckFullPage || "Full page";
      if (deckFullPageCb && ui.deckFullPageAria) deckFullPageCb.setAttribute("title", ui.deckFullPageAria);
      if (deckDashboardBtn) {{
        deckDashboardBtn.textContent = ui.deckBackDashboard || "Back to dashboard";
        if (ui.deckBackDashboardAria) deckDashboardBtn.setAttribute("aria-label", ui.deckBackDashboardAria);
      }}
      if (deckBrowseBtn) deckBrowseBtn.textContent = ui.deckBrowse || "Browse…";
      if (deckViewerTitle) deckViewerTitle.textContent = ui.deckViewerTitle || "Display";
      if (deckEmptyHint) deckEmptyHint.textContent = ui.deckEmptyHint || "";
      if (deckPdfFrame && ui.deckIframeTitle) deckPdfFrame.setAttribute("title", ui.deckIframeTitle);
      if (deckDownloadBtn) deckDownloadBtn.textContent = ui.deckDownloadCopy || "Download copy";
      function deckRevokeBlobUrls() {{
        deckBlobUrls.forEach(function (u) {{ try {{ URL.revokeObjectURL(u); }} catch (_e) {{}} }});
        deckBlobUrls = [];
        if (deckLastObjectUrl) {{
          try {{ URL.revokeObjectURL(deckLastObjectUrl); }} catch (_e2) {{}}
          deckLastObjectUrl = null;
        }}
      }}
      function deckDestroyPptxViewer() {{
        if (deckCanvasResizeTimer) {{
          try {{ clearTimeout(deckCanvasResizeTimer); }} catch (_ct) {{}}
          deckCanvasResizeTimer = null;
        }}
        deckClearSlideCoverTransform();
        if (deckPptxSvgViewer) {{
          try {{ deckPptxSvgViewer.destroy(); }} catch (_sd) {{}}
          deckPptxSvgViewer = null;
        }}
        if (deckPptxResizeObs) {{
          try {{ deckPptxResizeObs.disconnect(); }} catch (_ro) {{}}
          deckPptxResizeObs = null;
        }}
        deckPptxAspectRatio = null;
        if (deckPptxViewer) {{
          try {{ deckPptxViewer.destroy(); }} catch (_vd) {{}}
          deckPptxViewer = null;
        }}
      }}
      function deckPptxLoadStillCurrent(gen) {{
        return gen === deckPptxLoadGeneration;
      }}
      function deckGetSlideAspectRatio() {{
        try {{
          if (deckPptxSvgViewer && deckPptxSvgViewer.slideWidth > 0 && deckPptxSvgViewer.slideHeight > 0) {{
            return deckPptxSvgViewer.slideWidth / deckPptxSvgViewer.slideHeight;
          }}
        }} catch (_ga) {{}}
        return 16 / 9;
      }}
      function deckClearSlideCoverTransform() {{
        const host = document.querySelector("#audit-deck-pptx-host .audit-deck-svg-host");
        if (!host) return;
        for (let i = 0; i < host.children.length; i++) {{
          const ch = host.children[i];
          ch.style.transform = "";
          ch.style.transformOrigin = "";
          ch.style.willChange = "";
        }}
      }}
      function deckApplySlideCoverScale() {{
        const host = document.querySelector("#audit-deck-pptx-host .audit-deck-svg-host");
        if (!host || !deckPptxSvgViewer) return;
        deckClearSlideCoverTransform();
        const child = host.firstElementChild;
        if (!child) return;
        const hr = host.getBoundingClientRect();
        const cr = child.getBoundingClientRect();
        if (cr.width < 4 || cr.height < 4 || hr.width < 4 || hr.height < 4) return;
        const sx = hr.width / cr.width;
        const sy = hr.height / cr.height;
        const sContain = Math.min(sx, sy);
        const s = Math.min(1, sContain);
        if (Math.abs(s - 1) < 0.008) return;
        child.style.transformOrigin = "center center";
        child.style.willChange = "transform";
        child.style.transform = "scale(" + String(Math.round(s * 1000) / 1000) + ")";
      }}
      function deckComputeSlideWidthHint(svgHost) {{
        const pad = 12;
        const slideAspect = deckGetSlideAspectRatio();
        let r = svgHost.getBoundingClientRect();
        let W = Math.max(0, r.width - pad);
        let H = Math.max(0, r.height - pad);
        const inner = document.getElementById("audit-deck-viewer-inner");
        const ir = inner ? inner.getBoundingClientRect() : null;
        const root = svgHost.closest(".audit-deck-pptx-canvas-root");
        const rr = root ? root.getBoundingClientRect() : null;
        if (H < 160 || W < 200) {{
          if (rr && rr.height > 80) {{
            const chromeEst = 140;
            H = Math.max(H, Math.max(0, rr.height - chromeEst - pad));
          }}
          if (rr && rr.width > 80) {{
            W = Math.max(W, Math.max(0, rr.width - pad * 2));
          }}
        }}
        if (H < 160 && ir && ir.height > 100) {{
          const chromeEst = (deckModal && deckModal.classList.contains("audit-deck-modal--fill-page")) ? 100 : 200;
          H = Math.max(H, Math.max(160, ir.height - chromeEst - pad));
        }}
        if (W < 200 && ir && ir.width > 100) {{
          W = Math.max(W, Math.max(200, ir.width - pad * 2));
        }}
        if (H < 160) {{
          H = Math.max(H, Math.floor((window.innerHeight || 600) * 0.72) - pad);
        }}
        if (W < 200) {{
          W = Math.max(W, Math.floor((window.innerWidth || 1024) * 0.92) - pad);
        }}
        let w = 640;
        if (W > 0 && H > 0) {{
          const wFromHeight = H * slideAspect;
          w = Math.floor(Math.min(W, wFromHeight));
        }} else if (W > 0) {{
          w = Math.floor(W);
        }}
        w = Math.max(320, w || 640);
        const dpr = typeof window !== "undefined" && window.devicePixelRatio ? window.devicePixelRatio : 1;
        const inSlideShow = !!(deckModal && deckModal.classList.contains("audit-deck-modal--fill-page"));
        const sharp = inSlideShow
          ? Math.min(1.32, Math.max(1, Math.min(dpr, 1.35)))
          : Math.min(1.85, Math.max(1, dpr));
        return Math.min(1920, Math.floor(w * sharp));
      }}
      function deckRefitSvgToHost() {{
        if (!deckPptxSvgViewer) return;
        const svgHost = document.querySelector("#audit-deck-pptx-host .audit-deck-svg-host");
        if (!svgHost) return;
        deckClearSlideCoverTransform();
        const wHint = deckComputeSlideWidthHint(svgHost);
        const v = deckPptxSvgViewer;
        try {{
          if (typeof v.setSize === "function") v.setSize({{ width: wHint }});
          else if (typeof v.setOptions === "function") v.setOptions({{ width: wHint, fitMode: "contain" }});
          else if (typeof v.setWidth === "function") v.setWidth(wHint);
          else if (typeof v.resize === "function") v.resize(wHint);
        }} catch (_r0) {{}}
      }}
      function deckNotifyDeckLayoutResize() {{
        deckRefitSvgToHost();
        try {{ window.dispatchEvent(new Event("resize")); }} catch (_rz) {{}}
        requestAnimationFrame(function () {{
          deckRefitSvgToHost();
          requestAnimationFrame(deckApplySlideCoverScale);
        }});
        setTimeout(function () {{
          deckRefitSvgToHost();
          deckApplySlideCoverScale();
        }}, 200);
        setTimeout(deckApplySlideCoverScale, 500);
      }}
      function deckSyncToolbarSlideNavOnly() {{
        const tb = document.querySelector("#audit-deck-pptx-host .audit-deck-pptx-toolbar");
        if (!tb) return;
        const statusS = tb.querySelector(".audit-deck-pptx-status");
        const navBtns = tb.querySelectorAll("button.audit-deck-pptx-nav");
        const prevB = navBtns[0];
        const nextB = navBtns[1];
        try {{
          if (deckPptxSvgViewer && deckPptxSvgViewer.slideCount > 0) {{
            const cur = deckPptxSvgViewer.currentSlideIndex + 1;
            const tot = deckPptxSvgViewer.slideCount;
            const tpl0 = ui.deckSlideStatus;
            if (statusS) {{
              if (tpl0) {{
                statusS.textContent = String(tpl0)
                  .replace(/\\{{current\\}}/g, String(cur))
                  .replace(/\\{{total\\}}/g, String(tot));
              }} else {{
                statusS.textContent = String(cur) + " / " + String(tot);
              }}
            }}
            if (prevB) prevB.disabled = cur <= 1;
            if (nextB) nextB.disabled = cur >= tot;
          }} else if (deckPptxViewer) {{
            const cur = deckPptxViewer.getCurrentSlideIndex() + 1;
            const tot = deckPptxViewer.getSlideCount();
            const tpl0 = ui.deckSlideStatus;
            if (statusS) {{
              if (tpl0) {{
                statusS.textContent = String(tpl0)
                  .replace(/\\{{current\\}}/g, String(cur))
                  .replace(/\\{{total\\}}/g, String(tot));
              }} else {{
                statusS.textContent = String(cur) + " / " + String(tot);
              }}
            }}
            if (prevB) prevB.disabled = cur <= 1;
            if (nextB) nextB.disabled = cur >= tot;
          }}
        }} catch (_su) {{}}
      }}
      function deckOnGlobalKeydownSlides(ev) {{
        if (!deckModal || deckModal.style.display === "none") return;
        const rawT = ev.target;
        if (rawT && rawT.closest && rawT.closest("input, textarea, select, [contenteditable=true]")) return;
        if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
        const k = ev.key;
        const wantExit = k === "Escape";
        const wantToggleFullPage = k === "F11";
        const wantPrev = k === "ArrowLeft" || k === "ArrowUp" || k === "PageUp";
        const wantNext = k === "ArrowRight" || k === "ArrowDown" || k === "PageDown" || k === " " || k === "Enter";
        const wantFirst = k === "Home";
        const wantLast = k === "End";
        if (!wantExit && !wantToggleFullPage && !wantPrev && !wantNext && !wantFirst && !wantLast) return;
        if (wantExit) {{
          ev.preventDefault();
          if (typeof deckCloseModalAndReset === "function") deckCloseModalAndReset();
          return;
        }}
        if (wantToggleFullPage) {{
          ev.preventDefault();
          if (!deckFullPageCb) return;
          if (deckFullPageCb.checked) {{
            deckFullPageCb.checked = false;
            if (typeof deckCloseModalAndReset === "function") deckCloseModalAndReset();
          }} else {{
            deckFullPageCb.checked = true;
            deckApplyFullPageMode(true);
          }}
          return;
        }}
        const isPdfVisible = !!(deckPdfFrame && deckPdfFrame.style.display !== "none" && deckLastObjectUrl);
        if (!deckPptxSvgViewer && !deckPptxViewer && !isPdfVisible) return;
        ev.preventDefault();
        if (isPdfVisible && !deckPptxSvgViewer && !deckPptxViewer) {{
          if (wantFirst) deckSetPdfPage(1, false);
          else if (wantPrev) deckSetPdfPage(Math.max(1, deckPdfPage - 1), false);
          else if (wantNext) deckSetPdfPage(deckPdfPage + 1, false);
          return;
        }}
        if (deckPptxSvgViewer && deckPptxSvgViewer.slideCount > 0) {{
          const n = deckPptxSvgViewer.slideCount;
          let idx = deckPptxSvgViewer.currentSlideIndex;
          if (wantFirst) idx = 0;
          else if (wantLast) idx = n - 1;
          else if (wantPrev) idx = Math.max(0, idx - 1);
          else if (wantNext) idx = Math.min(n - 1, idx + 1);
          void deckPptxSvgViewer.goToSlide(idx).then(function () {{
            deckSyncToolbarSlideNavOnly();
            requestAnimationFrame(function () {{
              try {{ deckNotifyDeckLayoutResize(); }} catch (_eK0) {{}}
            }});
          }});
          return;
        }}
        if (deckPptxViewer) {{
          const canvas = document.querySelector("#audit-deck-pptx-host .audit-deck-pptx-canvas");
          if (!canvas) return;
          const n = deckPptxViewer.getSlideCount();
          let idx = deckPptxViewer.getCurrentSlideIndex();
          if (wantFirst) {{
            if (idx <= 0) {{ deckSyncToolbarSlideNavOnly(); return; }}
            (function stepPrev() {{
              if (!deckPptxViewer || deckPptxViewer.getCurrentSlideIndex() <= 0) {{
                deckSyncToolbarSlideNavOnly();
                requestAnimationFrame(function () {{
                  try {{ deckNotifyDeckLayoutResize(); }} catch (_eK1) {{}}
                }});
                return;
              }}
              void deckPptxViewer.previousSlide(canvas).then(stepPrev);
            }})();
            return;
          }}
          if (wantLast) {{
            if (idx >= n - 1) {{ deckSyncToolbarSlideNavOnly(); return; }}
            (function stepNext() {{
              if (!deckPptxViewer || deckPptxViewer.getCurrentSlideIndex() >= n - 1) {{
                deckSyncToolbarSlideNavOnly();
                requestAnimationFrame(function () {{
                  try {{ deckNotifyDeckLayoutResize(); }} catch (_eK2) {{}}
                }});
                return;
              }}
              void deckPptxViewer.nextSlide(canvas).then(stepNext);
            }})();
            return;
          }}
          if (wantPrev && idx > 0) {{
            void deckPptxViewer.previousSlide(canvas).then(function () {{
              deckSyncToolbarSlideNavOnly();
              requestAnimationFrame(function () {{
                try {{ deckNotifyDeckLayoutResize(); }} catch (_eK3) {{}}
              }});
            }});
          }} else if (wantNext && idx < n - 1) {{
            void deckPptxViewer.nextSlide(canvas).then(function () {{
              deckSyncToolbarSlideNavOnly();
              requestAnimationFrame(function () {{
                try {{ deckNotifyDeckLayoutResize(); }} catch (_eK4) {{}}
              }});
            }});
          }}
        }}
      }}
      function deckHandleRemoteKeyCommand(action) {{
        const keyByAction = {{
          prev: "ArrowLeft",
          next: "ArrowRight",
          first: "Home",
          last: "End",
          exit: "Escape",
          toggle_fullpage: "F11",
        }};
        const key = keyByAction[String(action || "").toLowerCase()];
        if (!key) return;
        deckOnGlobalKeydownSlides({{
          key: key,
          target: null,
          ctrlKey: false,
          metaKey: false,
          altKey: false,
          preventDefault: function () {{}},
        }});
      }}
      function deckClearSlideShowLayout() {{
        if (!deckModal) return;
        ["top", "left", "right", "bottom", "width", "height", "max-width", "max-height", "transform", "border-radius", "z-index"].forEach(function (k) {{
          try {{ deckModal.style.removeProperty(k); }} catch (_rk) {{}}
        }});
      }}
      function deckApplyFullPageMode(on) {{
        if (!deckModal) return;
        var want = !!on;
        deckModal.classList.toggle("audit-deck-modal--fill-page", want);
        if (deckDashboardExit) deckDashboardExit.setAttribute("aria-hidden", want ? "false" : "true");
        if (want) {{
          deckModal.style.setProperty("top", "0", "important");
          deckModal.style.setProperty("left", "0", "important");
          deckModal.style.setProperty("right", "0", "important");
          deckModal.style.setProperty("bottom", "0", "important");
          deckModal.style.setProperty("transform", "none", "important");
          deckModal.style.setProperty("width", "100%", "important");
          deckModal.style.setProperty("height", "100%", "important");
          deckModal.style.setProperty("max-width", "none", "important");
          deckModal.style.setProperty("max-height", "none", "important");
          deckModal.style.setProperty("border-radius", "0", "important");
          deckModal.style.setProperty("z-index", "10000", "important");
          var doResize = function () {{
            requestAnimationFrame(function () {{
              requestAnimationFrame(deckNotifyDeckLayoutResize);
            }});
          }};
          if (deckModal.requestFullscreen) {{
            deckModal.requestFullscreen().then(doResize).catch(doResize);
          }} else {{
            doResize();
          }}
        }} else {{
          if (document.fullscreenElement && (document.fullscreenElement === deckModal || (deckViewerInner && document.fullscreenElement === deckViewerInner))) {{
            try {{ document.exitFullscreen(); }} catch (_ex) {{}}
          }}
          deckClearSlideShowLayout();
          requestAnimationFrame(function () {{
            requestAnimationFrame(deckNotifyDeckLayoutResize);
          }});
        }}
      }}
      async function deckImportPptxRendererModule() {{
        const urls = [
          "https://esm.sh/@aiden0z/pptx-renderer@1.0.2",
          "https://cdn.jsdelivr.net/npm/@aiden0z/pptx-renderer@1.0.2/+esm",
        ];
        let lastErr = null;
        for (let uiu = 0; uiu < urls.length; uiu++) {{
          try {{
            return await import(urls[uiu]);
          }} catch (e) {{
            lastErr = e;
            await new Promise(function (r) {{ setTimeout(r, 400); }});
          }}
        }}
        throw lastErr || new Error("pptx-renderer import failed");
      }}
      const deckPdfStartZoom = 80;
      function deckPdfFragmentForPage(page) {{
        const p = Math.max(1, parseInt(page, 10) || 1);
        return "#page=" + String(p) + "&zoom=" + String(deckPdfStartZoom) + "&toolbar=1";
      }}
      function deckLoadPdfAtPage(page) {{
        if (!deckPdfFrame || !deckLastFile) return;
        const p = Math.max(1, parseInt(page, 10) || 1);
        const oldUrl = deckLastObjectUrl;
        deckPdfPage = p;
        deckLastObjectUrl = URL.createObjectURL(deckLastFile);
        const target = deckLastObjectUrl + deckPdfFragmentForPage(p);
        deckPdfFrame.src = "about:blank";
        setTimeout(function () {{
          try {{ deckPdfFrame.src = target; }} catch (_pdfSet0) {{}}
        }}, 20);
        if (oldUrl) {{
          setTimeout(function () {{
            try {{ URL.revokeObjectURL(oldUrl); }} catch (_rvPdf) {{}}
          }}, 1200);
        }}
      }}
      function deckSetPdfPage(page, forceReload) {{
        if (!deckPdfFrame || !deckLastFile) return;
        const p = Math.max(1, parseInt(page, 10) || 1);
        const targetSuffix = deckPdfFragmentForPage(p);
        const cur = String(deckPdfFrame.src || "");
        if (forceReload || cur.indexOf(targetSuffix) < 0) {{
          deckLoadPdfAtPage(p);
        }} else {{
          deckPdfPage = p;
        }}
      }}
      function deckResetViewerToFirstPage() {{
        if (deckPptxSvgViewer && deckPptxSvgViewer.slideCount > 0) {{
          void deckPptxSvgViewer.goToSlide(0).then(function () {{
            deckSyncToolbarSlideNavOnly();
            requestAnimationFrame(function () {{
              try {{ deckNotifyDeckLayoutResize(); }} catch (_rfs0) {{}}
            }});
          }});
          return;
        }}
        if (deckPptxViewer) {{
          const canvas = document.querySelector("#audit-deck-pptx-host .audit-deck-pptx-canvas");
          if (!canvas) return;
          (function stepPrev() {{
            if (!deckPptxViewer || deckPptxViewer.getCurrentSlideIndex() <= 0) {{
              deckSyncToolbarSlideNavOnly();
              requestAnimationFrame(function () {{
                try {{ deckNotifyDeckLayoutResize(); }} catch (_rfs1) {{}}
              }});
              return;
            }}
            void deckPptxViewer.previousSlide(canvas).then(stepPrev);
          }})();
          return;
        }}
        if (deckPdfFrame && deckPdfFrame.style.display !== "none" && deckLastFile) {{
          deckShowPdf(deckLastFile);
          requestAnimationFrame(function () {{ deckSetPdfPage(1, true); }});
        }}
      }}
      function deckClearViewer() {{
        deckDestroyPptxViewer();
        deckRevokeBlobUrls();
        if (deckPdfFrame) {{
          deckPdfFrame.style.display = "none";
          deckPdfFrame.src = "about:blank";
        }}
        if (deckPptxHost) {{
          deckPptxHost.style.display = "none";
          deckPptxHost.innerHTML = "";
        }}
        if (deckEmptyHint) deckEmptyHint.style.display = "block";
      }}
      function deckZipFind(zip, path) {{
        const zf = zip.file(path);
        if (zf) return zf;
        const low = path.replace(/\\\\/g, "/").toLowerCase();
        const hit = Object.keys(zip.files).find(function (k) {{
          return k.replace(/\\\\/g, "/").toLowerCase() === low;
        }});
        return hit ? zip.file(hit) : null;
      }}
      function deckResolvePart(baseDir, target) {{
        const stack = baseDir.replace(/\\\\/g, "/").replace(/\\/$/, "").split("/").filter(Boolean);
        String(target || "").replace(/\\\\/g, "/").split("/").forEach(function (p) {{
          if (p === "..") stack.pop();
          else if (p && p !== ".") stack.push(p);
        }});
        return stack.join("/");
      }}
      async function deckLoadRels(zip, relPath) {{
        const map = {{}};
        const f = deckZipFind(zip, relPath);
        if (!f) return map;
        const txt = await f.async("string");
        const doc = new DOMParser().parseFromString(txt, "text/xml");
        const relEls = doc.getElementsByTagName("Relationship");
        for (let i = 0; i < relEls.length; i++) {{
          const rel = relEls[i];
          const id = rel.getAttribute("Id");
          const type = rel.getAttribute("Type") || "";
          const target = rel.getAttribute("Target") || "";
          if (id) map[id] = {{ type: type, target: target }};
        }}
        return map;
      }}
      function deckSlideNum(path) {{
        const m = path.match(/slide(\\d+)\\.xml$/i);
        return m ? parseInt(m[1], 10) : 0;
      }}
      async function deckRenderPptxLegacy(file, deckGen, preloadedAb) {{
        if (!deckPptxLoadStillCurrent(deckGen)) return;
        if (!deckPptxHost || typeof JSZip === "undefined") {{
          if (deckEmptyHint) {{
            deckEmptyHint.style.display = "block";
            deckEmptyHint.textContent = ui.deckReadError || "";
          }}
          return;
        }}
        const engL = document.createElement("p");
        engL.className = "audit-deck-engine-status";
        engL.textContent = ui.deckEngineLegacy || "";
        deckPptxHost.appendChild(engL);
        const fbNote = document.createElement("p");
        fbNote.className = "audit-deck-pptx-note";
        fbNote.textContent = ui.deckPptxFallbackNote || "";
        deckPptxHost.appendChild(fbNote);
        let ab = preloadedAb;
        if (!ab || typeof ab.byteLength !== "number" || ab.byteLength <= 0) {{
          try {{
            ab = await file.arrayBuffer();
          }} catch (_e0) {{
            if (deckEmptyHint) {{
              deckEmptyHint.style.display = "block";
              deckEmptyHint.textContent = ui.deckReadError || "";
            }}
            return;
          }}
        }}
        if (!deckPptxLoadStillCurrent(deckGen)) return;
        let zip;
        try {{
          zip = await JSZip.loadAsync(ab);
        }} catch (_e1) {{
          if (deckEmptyHint) {{
            deckEmptyHint.style.display = "block";
            deckEmptyHint.textContent = ui.deckReadError || "";
          }}
          return;
        }}
        if (!deckPptxLoadStillCurrent(deckGen)) return;
        const thumbEntry = deckZipFind(zip, "docProps/thumbnail.jpeg");
        if (thumbEntry) {{
          const metaWrap = document.createElement("div");
          metaWrap.className = "audit-deck-deck-meta";
          const blob = await thumbEntry.async("blob");
          const url = URL.createObjectURL(blob);
          deckBlobUrls.push(url);
          const img = document.createElement("img");
          img.className = "audit-deck-thumb";
          img.src = url;
          img.alt = "";
          metaWrap.appendChild(img);
          deckPptxHost.appendChild(metaWrap);
        }}
        const slidePaths = Object.keys(zip.files)
          .filter(function (k) {{
            const kn = k.replace(/\\\\/g, "/");
            return /^ppt\\/slides\\/slide\\d+\\.xml$/i.test(kn) && kn.indexOf("_rels") < 0;
          }})
          .sort(function (a, b) {{ return deckSlideNum(a) - deckSlideNum(b); }});
        const headingTpl = ui.deckSlideHeading || "Slide {{n}}";
        const baseRelsDir = "ppt/slides/";
        for (let si = 0; si < slidePaths.length; si++) {{
          if (!deckPptxLoadStillCurrent(deckGen)) return;
          const sp = slidePaths[si].replace(/\\\\/g, "/");
          const sn = deckSlideNum(sp);
          const relFile = sp.replace(/([^/]+)\\.xml$/, "_rels/$1.xml.rels");
          const relMap = await deckLoadRels(zip, relFile);
          const sf = deckZipFind(zip, sp);
          if (!sf) continue;
          const xmlTxt = await sf.async("string");
          const embedIds = [];
          const reEmb = /(?:r:)?embed="(rId\\d+)"/g;
          let mm;
          while ((mm = reEmb.exec(xmlTxt)) !== null) embedIds.push(mm[1]);
          const seen = {{}};
          const orderedRids = [];
          embedIds.forEach(function (rid) {{
            if (!seen[rid]) {{ seen[rid] = true; orderedRids.push(rid); }}
          }});
          const texts = [];
          const reText = /<a:t[^>]*>([^<]*)<\\/a:t>/gi;
          while ((mm = reText.exec(xmlTxt)) !== null) {{
            const t = (mm[1] || "").trim();
            if (t) texts.push(t);
          }}
          const slideWrap = document.createElement("div");
          slideWrap.className = "audit-deck-slide";
          const headEl = document.createElement("div");
          headEl.className = "audit-deck-slide-head";
          const h5 = document.createElement("h5");
          h5.textContent = headingTpl.replace(/\\{{n\\}}/g, String(sn || si + 1));
          headEl.appendChild(h5);
          slideWrap.appendChild(headEl);
          const bodyEl = document.createElement("div");
          bodyEl.className = "audit-deck-slide-body";
          if (texts.length) {{
            const p = document.createElement("p");
            p.className = "audit-deck-slide-text";
            p.setAttribute("dir", "auto");
            p.textContent = texts.join(" ");
            bodyEl.appendChild(p);
          }}
          const imgsWrap = document.createElement("div");
          imgsWrap.className = "audit-deck-slide-imgs";
          let anyImg = false;
          for (let ri = 0; ri < orderedRids.length; ri++) {{
            const rid = orderedRids[ri];
            const meta = relMap[rid];
            if (!meta || !meta.target) continue;
            const isImage = meta.type.indexOf("image") >= 0 || /\\.(png|jpe?g|gif|bmp|webp|svg)$/i.test(meta.target);
            if (!isImage) continue;
            const abs = deckResolvePart(baseRelsDir, meta.target);
            const mf = deckZipFind(zip, abs);
            if (!mf) continue;
            const blob = await mf.async("blob");
            const url = URL.createObjectURL(blob);
            deckBlobUrls.push(url);
            const img = document.createElement("img");
            img.src = url;
            img.alt = "";
            imgsWrap.appendChild(img);
            anyImg = true;
          }}
          if (anyImg) {{
            const media = document.createElement("div");
            media.className = "audit-deck-slide-media";
            media.appendChild(imgsWrap);
            bodyEl.appendChild(media);
          }}
          if (!texts.length && !anyImg) {{
            const ph = document.createElement("p");
            ph.className = "audit-deck-slide-empty";
            ph.textContent = "—";
            bodyEl.appendChild(ph);
          }}
          slideWrap.appendChild(bodyEl);
          deckPptxHost.appendChild(slideWrap);
        }}
        if (!slidePaths.length && !thumbEntry) {{
          if (deckEmptyHint) {{
            deckEmptyHint.style.display = "block";
            deckEmptyHint.textContent = ui.deckReadError || "";
          }}
        }}
      }}
      async function deckRenderPptx(file) {{
        if (!deckPptxHost) return;
        deckDestroyPptxViewer();
        deckRevokeBlobUrls();
        const deckLoadGen = ++deckPptxLoadGeneration;
        deckPptxHost.innerHTML = "";
        deckPptxHost.style.display = "flex";
        if (deckEmptyHint) deckEmptyHint.style.display = "none";
        let deckAb;
        try {{
          deckAb = await file.arrayBuffer();
        }} catch (_ab0) {{
          if (deckEmptyHint) {{
            deckEmptyHint.style.display = "block";
            deckEmptyHint.textContent = ui.deckReadError || "";
          }}
          return;
        }}
        if (!deckPptxLoadStillCurrent(deckLoadGen)) return;
        let deckPptxUsedEngine = false;
        try {{
          const prMod = await deckImportPptxRendererModule();
          if (!deckPptxLoadStillCurrent(deckLoadGen)) return;
          const PVSvg = prMod.PptxViewer;
          if (PVSvg && typeof PVSvg.open === "function") {{
            const noteTextSvg = String(ui.deckPptxNote || "").trim();
            if (noteTextSvg) {{
              const m0 = document.createElement("div");
              m0.className = "audit-deck-deck-meta";
              const n0 = document.createElement("p");
              n0.className = "audit-deck-pptx-note";
              n0.textContent = noteTextSvg;
              m0.appendChild(n0);
              deckPptxHost.appendChild(m0);
            }}
            const rootS = document.createElement("div");
            rootS.className = "audit-deck-pptx-canvas-root";
            const engS = document.createElement("p");
            engS.className = "audit-deck-engine-status";
            engS.textContent = ui.deckEngineSvg || "";
            rootS.appendChild(engS);
            const tbS = document.createElement("div");
            tbS.className = "audit-deck-pptx-toolbar";
            const prevS = document.createElement("button");
            prevS.type = "button";
            prevS.className = "audit-deck-pptx-nav";
            prevS.textContent = ui.deckSlidePrev || "Previous slide";
            if (ui.deckSlidePrev) prevS.setAttribute("aria-label", ui.deckSlidePrev);
            const nextS = document.createElement("button");
            nextS.type = "button";
            nextS.className = "audit-deck-pptx-nav";
            nextS.textContent = ui.deckSlideNext || "Next slide";
            if (ui.deckSlideNext) nextS.setAttribute("aria-label", ui.deckSlideNext);
            const statusS = document.createElement("span");
            statusS.className = "audit-deck-pptx-status";
            statusS.setAttribute("aria-live", "polite");
            tbS.appendChild(prevS);
            tbS.appendChild(statusS);
            tbS.appendChild(nextS);
            const zoomBar = document.createElement("div");
            zoomBar.className = "audit-deck-pptx-zoombar";
            const zoomOut = document.createElement("button");
            zoomOut.type = "button";
            zoomOut.className = "audit-deck-pptx-nav";
            zoomOut.textContent = "−";
            if (ui.deckZoomOut) zoomOut.setAttribute("aria-label", ui.deckZoomOut);
            const zoomLbl = document.createElement("span");
            zoomLbl.className = "audit-deck-pptx-zoom-lbl";
            zoomLbl.textContent = "100%";
            if (ui.deckZoomLabel) zoomLbl.setAttribute("title", ui.deckZoomLabel);
            const zoomIn = document.createElement("button");
            zoomIn.type = "button";
            zoomIn.className = "audit-deck-pptx-nav";
            zoomIn.textContent = "+";
            if (ui.deckZoomIn) zoomIn.setAttribute("aria-label", ui.deckZoomIn);
            const zoomReset = document.createElement("button");
            zoomReset.type = "button";
            zoomReset.className = "audit-deck-pptx-nav";
            zoomReset.textContent = ui.deckZoomReset || "Reset";
            if (ui.deckZoomReset) zoomReset.setAttribute("aria-label", ui.deckZoomReset);
            zoomBar.appendChild(zoomOut);
            zoomBar.appendChild(zoomLbl);
            zoomBar.appendChild(zoomIn);
            zoomBar.appendChild(zoomReset);
            const svgHost = document.createElement("div");
            svgHost.className = "audit-deck-svg-host";
            svgHost.setAttribute("dir", document.documentElement.getAttribute("dir") || "ltr");
            rootS.appendChild(tbS);
            rootS.appendChild(zoomBar);
            rootS.appendChild(svgHost);
            deckPptxHost.appendChild(rootS);
            await new Promise(function (resolve) {{
              requestAnimationFrame(function () {{ requestAnimationFrame(resolve); }});
            }});
            if (!deckPptxLoadStillCurrent(deckLoadGen)) return;
            const wHint = deckComputeSlideWidthHint(svgHost);
            const openOpts = {{
              renderMode: "slide",
              fitMode: "contain",
              width: wHint,
            }};
            try {{
              deckPptxSvgViewer = await PVSvg.open(deckAb, svgHost, openOpts);
            }} catch (_op1) {{
              const VCls = PVSvg;
              const v2 = new VCls(svgHost, {{ fitMode: "contain", width: wHint }});
              try {{
                await v2.open(deckAb, {{ renderMode: "slide" }});
                deckPptxSvgViewer = v2;
              }} catch (_op2) {{
                try {{ v2.destroy(); }} catch (_d2) {{}}
                throw _op2;
              }}
            }}
            if (!deckPptxLoadStillCurrent(deckLoadGen)) {{
              if (deckPptxSvgViewer) {{
                try {{ deckPptxSvgViewer.destroy(); }} catch (_st) {{}}
                deckPptxSvgViewer = null;
              }}
              return;
            }}
            function deckSyncSvgNav() {{
              if (!deckPptxLoadStillCurrent(deckLoadGen)) return;
              if (!deckPptxSvgViewer) return;
              const cur = deckPptxSvgViewer.currentSlideIndex + 1;
              const tot = deckPptxSvgViewer.slideCount;
              const tplS = ui.deckSlideStatus;
              if (tplS) {{
                statusS.textContent = String(tplS)
                  .replace(/\\{{current\\}}/g, String(cur))
                  .replace(/\\{{total\\}}/g, String(tot));
              }} else {{
                statusS.textContent = String(cur) + " / " + String(tot);
              }}
              prevS.disabled = cur <= 1;
              nextS.disabled = cur >= tot;
            }}
            deckSyncSvgNav();
            prevS.addEventListener("click", function () {{
              if (!deckPptxLoadStillCurrent(deckLoadGen) || !deckPptxSvgViewer) return;
              const i = deckPptxSvgViewer.currentSlideIndex;
              if (i > 0) void deckPptxSvgViewer.goToSlide(i - 1).then(deckSyncSvgNav);
            }});
            nextS.addEventListener("click", function () {{
              if (!deckPptxLoadStillCurrent(deckLoadGen) || !deckPptxSvgViewer) return;
              const i = deckPptxSvgViewer.currentSlideIndex;
              const nTot = deckPptxSvgViewer.slideCount;
              if (i < nTot - 1) void deckPptxSvgViewer.goToSlide(i + 1).then(deckSyncSvgNav);
            }});
            deckPptxSvgViewer.addEventListener("slidechange", function () {{
              deckSyncSvgNav();
              requestAnimationFrame(function () {{
                deckRefitSvgToHost();
                requestAnimationFrame(deckApplySlideCoverScale);
              }});
            }});
            function deckSyncSvgZoomLbl() {{
              if (!deckPptxLoadStillCurrent(deckLoadGen) || !deckPptxSvgViewer) return;
              const zp = deckPptxSvgViewer.zoomPercent;
              if (typeof zp === "number") zoomLbl.textContent = String(zp) + "%";
            }}
            deckSyncSvgZoomLbl();
            zoomOut.addEventListener("click", function () {{
              if (!deckPptxLoadStillCurrent(deckLoadGen) || !deckPptxSvgViewer || typeof deckPptxSvgViewer.setZoom !== "function") return;
              const curZ = deckPptxSvgViewer.zoomPercent || 100;
              void Promise.resolve(deckPptxSvgViewer.setZoom(Math.max(50, curZ - 10))).then(function () {{
                deckSyncSvgZoomLbl();
                requestAnimationFrame(deckApplySlideCoverScale);
              }});
            }});
            zoomIn.addEventListener("click", function () {{
              if (!deckPptxLoadStillCurrent(deckLoadGen) || !deckPptxSvgViewer || typeof deckPptxSvgViewer.setZoom !== "function") return;
              const curZ = deckPptxSvgViewer.zoomPercent || 100;
              void Promise.resolve(deckPptxSvgViewer.setZoom(Math.min(300, curZ + 10))).then(function () {{
                deckSyncSvgZoomLbl();
                requestAnimationFrame(deckApplySlideCoverScale);
              }});
            }});
            zoomReset.addEventListener("click", function () {{
              if (!deckPptxLoadStillCurrent(deckLoadGen) || !deckPptxSvgViewer || typeof deckPptxSvgViewer.setZoom !== "function") return;
              void Promise.resolve(deckPptxSvgViewer.setZoom(100)).then(function () {{
                deckSyncSvgZoomLbl();
                requestAnimationFrame(deckApplySlideCoverScale);
              }});
            }});
            try {{
              deckPptxSvgViewer.addEventListener("rendercomplete", function () {{
                deckSyncSvgZoomLbl();
                requestAnimationFrame(function () {{
                  requestAnimationFrame(deckApplySlideCoverScale);
                }});
              }});
            }} catch (_zEv) {{}}
            deckNotifyDeckLayoutResize();
            deckPptxUsedEngine = true;
          }}
        }} catch (_svgEx) {{
          if (deckPptxSvgViewer) {{
            try {{ deckPptxSvgViewer.destroy(); }} catch (_sx) {{}}
            deckPptxSvgViewer = null;
          }}
          if (!deckPptxLoadStillCurrent(deckLoadGen)) return;
          deckPptxHost.innerHTML = "";
          deckPptxHost.style.display = "flex";
          if (deckEmptyHint) deckEmptyHint.style.display = "none";
        }}
        if (deckPptxUsedEngine) return;
        if (!deckPptxLoadStillCurrent(deckLoadGen)) return;
        const Pvz = typeof PptxViewJS !== "undefined" ? PptxViewJS : null;
        if (Pvz && Pvz.PPTXViewer) {{
          try {{
            const noteText0 = String(ui.deckPptxNote || "").trim();
            if (noteText0) {{
              const metaWrap0 = document.createElement("div");
              metaWrap0.className = "audit-deck-deck-meta";
              const noteEl0 = document.createElement("p");
              noteEl0.className = "audit-deck-pptx-note";
              noteEl0.textContent = noteText0;
              metaWrap0.appendChild(noteEl0);
              deckPptxHost.appendChild(metaWrap0);
            }}
            const root = document.createElement("div");
            root.className = "audit-deck-pptx-canvas-root";
            const engC = document.createElement("p");
            engC.className = "audit-deck-engine-status";
            engC.textContent = ui.deckEngineCanvas || "";
            root.appendChild(engC);
            const tb = document.createElement("div");
            tb.className = "audit-deck-pptx-toolbar";
            const prevBtn = document.createElement("button");
            prevBtn.type = "button";
            prevBtn.className = "audit-deck-pptx-nav";
            prevBtn.textContent = ui.deckSlidePrev || "Previous slide";
            if (ui.deckSlidePrev) prevBtn.setAttribute("aria-label", ui.deckSlidePrev);
            const nextBtn = document.createElement("button");
            nextBtn.type = "button";
            nextBtn.className = "audit-deck-pptx-nav";
            nextBtn.textContent = ui.deckSlideNext || "Next slide";
            if (ui.deckSlideNext) nextBtn.setAttribute("aria-label", ui.deckSlideNext);
            const statusEl = document.createElement("span");
            statusEl.className = "audit-deck-pptx-status";
            statusEl.setAttribute("aria-live", "polite");
            tb.appendChild(prevBtn);
            tb.appendChild(statusEl);
            tb.appendChild(nextBtn);
            const cvWrap = document.createElement("div");
            cvWrap.className = "audit-deck-pptx-canvas-wrap";
            const canvas = document.createElement("canvas");
            canvas.className = "audit-deck-pptx-canvas";
            canvas.setAttribute("role", "img");
            if (ui.deckIframeTitle) canvas.setAttribute("aria-label", ui.deckIframeTitle);
            cvWrap.appendChild(canvas);
            root.appendChild(tb);
            root.appendChild(cvWrap);
            deckPptxHost.appendChild(root);
            await new Promise(function (resolve) {{
              requestAnimationFrame(function () {{ requestAnimationFrame(resolve); }});
            }});
            if (!deckPptxLoadStillCurrent(deckLoadGen)) return;
            (function () {{
              const pad = 20;
              const fallbackAspect = 16 / 9;
              const rw0 = cvWrap.clientWidth;
              const rh0 = cvWrap.clientHeight;
              let w0;
              if (rw0 > 0 && rh0 > 40) {{
                const wFromW = rw0 - pad;
                const wFromH = (rh0 - pad) * fallbackAspect;
                w0 = Math.floor(Math.min(wFromW, wFromH));
              }} else {{
                w0 = rw0 > 0 ? rw0 - pad : 640;
              }}
              w0 = Math.max(280, w0);
              canvas.style.width = w0 + "px";
              canvas.style.height = Math.round(w0 / fallbackAspect) + "px";
            }})();
            deckPptxViewer = new Pvz.PPTXViewer({{
              canvas: canvas,
              slideSizeMode: "fit",
              backgroundColor: "#ffffff",
              autoChartRerenderDelayMs: 450
            }});
            await deckPptxViewer.loadFile(deckAb);
            if (!deckPptxLoadStillCurrent(deckLoadGen)) return;
            try {{
              await deckPptxViewer.render(canvas, {{ quality: "high" }});
            }} catch (_rq) {{
              await deckPptxViewer.render(canvas);
            }}
            if (!deckPptxLoadStillCurrent(deckLoadGen)) return;
            (function () {{
              const sw = parseFloat(canvas.style.width);
              const sh = parseFloat(canvas.style.height);
              if (sw > 0 && sh > 0) deckPptxAspectRatio = sw / sh;
            }})();
            function deckSyncPptxNav() {{
              if (!deckPptxLoadStillCurrent(deckLoadGen) || !deckPptxViewer) return;
              const cur = deckPptxViewer.getCurrentSlideIndex() + 1;
              const tot = deckPptxViewer.getSlideCount();
              const tpl0 = ui.deckSlideStatus;
              if (tpl0) {{
                statusEl.textContent = String(tpl0)
                  .replace(/\\{{current\\}}/g, String(cur))
                  .replace(/\\{{total\\}}/g, String(tot));
              }} else {{
                statusEl.textContent = String(cur) + " / " + String(tot);
              }}
              prevBtn.disabled = cur <= 1;
              nextBtn.disabled = cur >= tot;
            }}
            deckSyncPptxNav();
            prevBtn.addEventListener("click", function () {{
              if (!deckPptxLoadStillCurrent(deckLoadGen) || !deckPptxViewer) return;
              void deckPptxViewer.previousSlide(canvas).then(deckSyncPptxNav);
            }});
            nextBtn.addEventListener("click", function () {{
              if (!deckPptxLoadStillCurrent(deckLoadGen) || !deckPptxViewer) return;
              void deckPptxViewer.nextSlide(canvas).then(deckSyncPptxNav);
            }});
            if (typeof ResizeObserver !== "undefined") {{
              deckPptxResizeObs = new ResizeObserver(function () {{
                if (deckCanvasResizeTimer) try {{ clearTimeout(deckCanvasResizeTimer); }} catch (_c0) {{}}
                deckCanvasResizeTimer = setTimeout(function () {{
                  deckCanvasResizeTimer = null;
                  if (!deckPptxLoadStillCurrent(deckLoadGen)) return;
                  if (!deckPptxViewer || !deckPptxAspectRatio) return;
                  const pad2 = 20;
                  const rw2 = cvWrap.clientWidth;
                  const rh2 = cvWrap.clientHeight;
                  const ar = deckPptxAspectRatio;
                  let nw;
                  if (rw2 > 0 && rh2 > 40) {{
                    const wFromW = rw2 - pad2;
                    const wFromH = (rh2 - pad2) * ar;
                    nw = Math.floor(Math.min(wFromW, wFromH));
                  }} else {{
                    nw = rw2 > 0 ? rw2 - pad2 : 640;
                  }}
                  nw = Math.max(240, nw);
                  const nh = Math.round(nw / ar);
                  canvas.style.width = nw + "px";
                  canvas.style.height = nh + "px";
                  void deckPptxViewer.render(canvas).then(deckSyncPptxNav);
                }}, 160);
              }});
              deckPptxResizeObs.observe(cvWrap);
            }}
            return;
          }} catch (_pc) {{
            deckDestroyPptxViewer();
            if (!deckPptxLoadStillCurrent(deckLoadGen)) return;
            deckPptxHost.innerHTML = "";
            deckPptxHost.style.display = "flex";
            if (deckEmptyHint) deckEmptyHint.style.display = "none";
          }}
        }}
        if (!deckPptxLoadStillCurrent(deckLoadGen)) return;
        await deckRenderPptxLegacy(file, deckLoadGen, deckAb);
      }}
      function deckCloseModalAndReset() {{
        var wasSlideShow = false;
        try {{
          if (deckModal && deckModal.style.display !== "none") {{
            wasSlideShow = deckModal.classList.contains("audit-deck-modal--fill-page")
              || !!(deckFullPageCb && deckFullPageCb.checked)
              || !!(document.fullscreenElement && deckModal && (document.fullscreenElement === deckModal || (deckViewerInner && document.fullscreenElement === deckViewerInner)));
          }}
        }} catch (_ws) {{}}
        if (deckFullPageCb) deckFullPageCb.checked = false;
        if (document.fullscreenElement && deckModal && (document.fullscreenElement === deckModal || (deckViewerInner && document.fullscreenElement === deckViewerInner))) {{
          try {{ document.exitFullscreen(); }} catch (_ex2) {{}}
        }}
        deckClearSlideShowLayout();
        if (deckModal) deckModal.classList.remove("audit-deck-modal--fill-page");
        if (deckDashboardExit) deckDashboardExit.setAttribute("aria-hidden", "true");
        if (deckBackdrop) {{
          deckBackdrop.style.display = "none";
          deckBackdrop.setAttribute("aria-hidden", "true");
        }}
        if (deckModal) {{
          deckModal.style.display = "none";
          deckModal.setAttribute("aria-hidden", "true");
        }}
        try {{
          if (window.parent && window.parent !== window) {{
            window.parent.postMessage({{ type: "deck-modal-state", open: false }}, "*");
          }}
        }} catch (_pm0) {{}}
        try {{ document.body.classList.remove("audit-deck-open"); }} catch (_bco) {{}}
        if (deckLastFile) deckFilesByMode[deckPanelMode] = deckLastFile;
        if (deckAttachCb) deckAttachCb.checked = false;
        if (highRiskCb) highRiskCb.checked = false;
        if (tgaViolationsCb) tgaViolationsCb.checked = false;
        if (missingVehicleCb) missingVehicleCb.checked = false;
        if (internalAuditQuarterlyCb) internalAuditQuarterlyCb.checked = false;
        if (specialAssignmentCb) specialAssignmentCb.checked = false;
        if (deckFileInput) deckFileInput.value = "";
        deckSetUploadFirstMode(false);
        deckClearViewer();
        if (deckFilename) deckFilename.style.display = "none";
        if (deckDownloadBtn) deckDownloadBtn.style.display = "none";
        deckLastFile = null;
        deckPanelMode = "committee";
        if (wasSlideShow) {{
          try {{ window.scrollTo({{ top: 0, left: 0, behavior: "auto" }}); }} catch (_sc) {{
            try {{ window.scrollTo(0, 0); }} catch (_sc2) {{}}
          }}
        }}
      }}
      function applyEmbeddedDeckForCompanySelection() {{
        if (deckPanelMode !== "committee") return;
        const ed = payload.embedded_slide_deck;
        if (!ed) return;
        let entry = null;
        let sig = null;
        if (ed.by_company) {{
          const coSel = typeof companyFilterSelectEl === "function" ? companyFilterSelectEl() : null;
          let picked = [];
          if (coSel && coSel.selectedOptions) {{
            picked = Array.from(coSel.selectedOptions).map(function (o) {{
              return String(o.value != null ? o.value : o.textContent || "").trim();
            }}).filter(function (x) {{ return x !== ""; }});
          }}
          picked.sort(function (a, b) {{ return String(a).localeCompare(String(b)); }});
          if (picked.length === 1 && ed.by_company[picked[0]]) {{
            entry = ed.by_company[picked[0]];
            sig = "co:" + picked[0];
          }} else if (ed.fallback) {{
            entry = ed.fallback;
            sig = "fb";
          }} else {{
            sig = "none";
          }}
        }} else if (ed.data_base64) {{
          entry = ed;
          sig = "legacy";
        }}
        if (!entry || !entry.data_base64) {{
          if (sig === "none" && ed.by_company) {{
            embeddedDeckLoadSig = sig;
            deckClearViewer();
            deckLastFile = null;
            if (deckFilename) deckFilename.style.display = "none";
            if (deckDownloadBtn) deckDownloadBtn.style.display = "none";
          }}
          return;
        }}
        if (sig === embeddedDeckLoadSig && deckLastFile) {{
          try {{ deckResetViewerToFirstPage(); }} catch (_r0) {{}}
          return;
        }}
        embeddedDeckLoadSig = sig;
        deckClearViewer();
        deckLastFile = null;
        try {{
          const raw = atob(entry.data_base64);
          const len = raw.length;
          const u8 = new Uint8Array(len);
          for (let i = 0; i < len; i++) u8[i] = raw.charCodeAt(i);
          const mime =
            entry.mime || "application/vnd.openxmlformats-officedocument.presentationml.presentation";
          const blob = new Blob([u8], {{ type: mime }});
          const name = entry.file_name || "slides.pptx";
          const f = new File([blob], name, {{ type: mime }});
          void deckHandleFile(f);
        }} catch (_re) {{}}
      }}
      function rehydrateEmbeddedSlideDeckIfNeeded() {{
        applyEmbeddedDeckForCompanySelection();
      }}
      function openDeckModal() {{
        if (!deckModal || !deckBackdrop) return;
        deckApplyPanelChrome();
        try {{ document.body.classList.add("audit-deck-open"); }} catch (_bco2) {{}}
        try {{
          if (window.parent && window.parent !== window) {{
            window.parent.postMessage({{ type: "deck-modal-state", open: true }}, "*");
          }}
        }} catch (_pm1) {{}}
        deckBackdrop.style.display = "block";
        deckBackdrop.setAttribute("aria-hidden", "false");
        deckModal.style.display = "block";
        deckModal.setAttribute("aria-hidden", "false");
        if (deckIsAltMode()) {{
          deckSetUploadFirstMode(false);
          deckPromptUploadIfNeeded();
        }} else {{
          deckSetUploadFirstMode(false);
          try {{
            if (deckFullPageCb) deckFullPageCb.checked = true;
            deckApplyFullPageMode(true);
          }} catch (_fm0) {{}}
          rehydrateEmbeddedSlideDeckIfNeeded();
          setTimeout(function () {{
            try {{ deckResetViewerToFirstPage(); }} catch (_rfsp) {{}}
          }}, 120);
        }}
        try {{
          if (!deckModal.hasAttribute("tabindex")) deckModal.setAttribute("tabindex", "-1");
        }} catch (_tb) {{}}
        requestAnimationFrame(function () {{ try {{ deckNotifyDeckLayoutResize(); }} catch (_rz0) {{}} }});
        try {{
          if (deckModal && typeof deckModal.focus === "function") deckModal.focus({{ preventScroll: true }});
          else if (deckModalClose) deckModalClose.focus();
        }} catch (_fc) {{
          if (deckModalClose) deckModalClose.focus();
        }}
      }}
      function deckSyncPanel() {{
        if (!deckAttachCb) return;
        if (deckAttachCb.checked) {{
          tryOpenDeckAttachMode("committee", deckAttachCb);
        }} else if (deckPanelMode === "committee") deckCloseModalAndReset();
      }}
      function makeAltDeckSyncPanel(cb, mode) {{
        return function () {{
          if (!cb) return;
          if (cb.checked) {{
            tryOpenDeckAttachMode(mode, cb);
          }} else if (deckPanelMode === mode) deckCloseModalAndReset();
        }};
      }}
      const highRiskDeckSyncPanel = makeAltDeckSyncPanel(highRiskCb, "highRisk");
      const tgaViolationsDeckSyncPanel = makeAltDeckSyncPanel(tgaViolationsCb, "tgaViolations");
      const missingVehicleDeckSyncPanel = makeAltDeckSyncPanel(missingVehicleCb, "missingVehicle");
      const internalAuditQuarterlyDeckSyncPanel = makeAltDeckSyncPanel(internalAuditQuarterlyCb, "internalAuditQuarterly");
      const specialAssignmentDeckSyncPanel = makeAltDeckSyncPanel(specialAssignmentCb, "specialAssignment");
      function deckShowPdf(file) {{
        if (!deckPdfFrame) return;
        deckDestroyPptxViewer();
        deckRevokeBlobUrls();
        if (deckPptxHost) {{
          deckPptxHost.style.display = "none";
          deckPptxHost.innerHTML = "";
        }}
        if (deckEmptyHint) deckEmptyHint.style.display = "none";
        deckLastFile = file;
        deckPdfPage = 1;
        deckPdfFrame.style.display = "block";
        deckLoadPdfAtPage(1);
        try {{
          if (!deckPdfFrame.hasAttribute("tabindex")) deckPdfFrame.setAttribute("tabindex", "-1");
          deckPdfFrame.focus();
        }} catch (_pf0) {{}}
      }}
      async function deckHandleFile(f) {{
        if (!f) return;
        deckFilesByMode[deckPanelMode] = f;
        deckLastFile = f;
        deckSetUploadFirstMode(false);
        if (deckFilename) {{
          deckFilename.textContent = f.name || "";
          deckFilename.style.display = "block";
        }}
        if (deckDownloadBtn) deckDownloadBtn.style.display = "inline-flex";
        const name = String(f.name || "").toLowerCase();
        const mime = String(f.type || "").toLowerCase();
        if (name.endsWith(".pdf") || mime === "application/pdf") {{
          deckShowPdf(f);
          deckFinishAltDeckPresentation();
          return;
        }}
        if (name.endsWith(".ppt")) {{
          deckClearViewer();
          if (deckEmptyHint) {{
            deckEmptyHint.style.display = "block";
            deckEmptyHint.textContent = ui.deckPptLegacyWarn || "";
          }}
          return;
        }}
        if (name.endsWith(".pptx") || mime.indexOf("presentationml") >= 0) {{
          if (deckPdfFrame) {{
            deckPdfFrame.style.display = "none";
            deckPdfFrame.src = "about:blank";
          }}
          await deckRenderPptx(f);
          deckFinishAltDeckPresentation();
          return;
        }}
        deckClearViewer();
        if (deckEmptyHint) {{
          deckEmptyHint.style.display = "block";
          deckEmptyHint.textContent = ui.deckUploadHint || "";
        }}
      }}
      function bindAltDeckToggle(cb, syncFn) {{
        if (!cb || !syncFn) return;
        cb.addEventListener("change", syncFn);
        cb.addEventListener("click", function () {{
          queueMicrotask(syncFn);
        }});
      }}
      if (deckAttachCb) {{
        deckAttachCb.addEventListener("change", deckSyncPanel);
        deckAttachCb.addEventListener("click", function () {{
          queueMicrotask(deckSyncPanel);
        }});
      }}
      bindAltDeckToggle(highRiskCb, highRiskDeckSyncPanel);
      bindAltDeckToggle(tgaViolationsCb, tgaViolationsDeckSyncPanel);
      bindAltDeckToggle(missingVehicleCb, missingVehicleDeckSyncPanel);
      bindAltDeckToggle(internalAuditQuarterlyCb, internalAuditQuarterlyDeckSyncPanel);
      bindAltDeckToggle(specialAssignmentCb, specialAssignmentDeckSyncPanel);
      if (deckMissingOk) deckMissingOk.addEventListener("click", deckCloseNoAttachmentNotice);
      if (deckMissingBackdrop) deckMissingBackdrop.addEventListener("click", deckCloseNoAttachmentNotice);
      document.addEventListener("keydown", function (ev) {{
        if (!ev || ev.key !== "Escape") return;
        if (!deckMissingPanel || deckMissingPanel.style.display === "none") return;
        ev.preventDefault();
        deckCloseNoAttachmentNotice();
      }});
      if (deckUploadLayerBrowse && deckFileInput) {{
        deckUploadLayerBrowse.addEventListener("click", function () {{
          try {{ deckFileInput.click(); }} catch (_ulb) {{}}
        }});
      }}
      if (deckFullPageCb) {{
        deckFullPageCb.addEventListener("change", function () {{
          if (deckFullPageCb.checked) {{
            deckApplyFullPageMode(true);
          }} else if (typeof deckCloseModalAndReset === "function") {{
            deckCloseModalAndReset();
          }}
        }});
      }}
      document.addEventListener("fullscreenchange", function () {{
        if (!deckFullPageCb || !deckModal) return;
        if (deckModal.style.display === "none") return;
        if (document.fullscreenElement) return;
        if (!deckFullPageCb.checked) return;
        if (typeof deckCloseModalAndReset === "function") deckCloseModalAndReset();
      }});
      if (deckModalClose) deckModalClose.addEventListener("click", deckCloseModalAndReset);
      if (deckDashboardBtn) deckDashboardBtn.addEventListener("click", deckCloseModalAndReset);
      if (deckBackdrop) deckBackdrop.addEventListener("click", deckCloseModalAndReset);
      if (deckBrowseBtn && deckFileInput) {{
        deckBrowseBtn.addEventListener("click", function () {{ deckFileInput.click(); }});
      }}
      if (deckFileInput) {{
        deckFileInput.addEventListener("change", function () {{
          const f = deckFileInput.files && deckFileInput.files[0];
          void deckHandleFile(f);
        }});
      }}
      if (deckPdfFrame) {{
        deckPdfFrame.addEventListener("load", function () {{
          if (!deckLastFile || deckPdfFrame.style.display === "none") return;
          const cur = String(deckPdfFrame.src || "");
          const expected = deckPdfFragmentForPage(deckPdfPage);
          if (cur.indexOf(expected) < 0) {{
            deckSetPdfPage(deckPdfPage, true);
          }}
        }});
      }}
      if (deckDownloadBtn) {{
        deckDownloadBtn.addEventListener("click", function () {{
          if (!deckLastFile) return;
          const u = URL.createObjectURL(deckLastFile);
          const a = document.createElement("a");
          a.href = u;
          a.download = deckLastFile.name || "document";
          document.body.appendChild(a);
          a.click();
          a.remove();
          setTimeout(function () {{ try {{ URL.revokeObjectURL(u); }} catch (_e3) {{}} }}, 4000);
        }});
      }}
      window.addEventListener("keydown", deckOnGlobalKeydownSlides, {{ capture: true }});
      window.addEventListener("message", function (ev) {{
        const data = ev && ev.data ? ev.data : null;
        if (!data || data.type !== "deck-key-command") return;
        deckHandleRemoteKeyCommand(data.action);
      }});
      if (planAddRowBtn) planAddRowBtn.addEventListener("click", appendPlanEmptyRow);
      if (planDownloadPptBtn) {{
        planDownloadPptBtn.addEventListener("click", function () {{
          if (typeof PptxGenJS === "undefined") return;
          const pptx = new PptxGenJS();
          pptx.layout = "LAYOUT_WIDE";
          const slide = pptx.addSlide();
          slide.background = {{ color: "F1F5F9" }};
          slide.addText(ui.planTitle || "Audit Plan Status", {{ x: 0.35, y: 0.2, w: 12.5, h: 0.35, fontFace: "Arial", bold: true, fontSize: 18, color: "0F172A" }});
          const cols = [
            ui.planColProjectName || "Project Name",
            ui.planColAuditableFunction || "Auditable function",
            ui.planColResourceAllocated || "Resource Allocated",
            ui.planColProjectStatus || "Project Status",
            ui.planColPlanningPct || "Planning %",
            ui.planColFieldWorkPct || "Field Work %",
            ui.planColReportingPct || "Reporting %",
          ];
          const tableRows = [cols];
          const many = getPlanDraftRows() || [["", "", "", "", "", "", ""]];
          many.forEach(function (r) {{ tableRows.push(r); }});
          slide.addTable(tableRows, {{
            x: 0.3, y: 0.75, w: 12.7, h: 1.8,
            border: {{ type: "solid", color: "94A3B8", pt: 1 }},
            fontFace: "Arial",
            fontSize: 11,
            color: "0F172A",
            fill: "FFFFFF",
            valign: "middle",
            colW: [2.1, 3.0, 1.6, 1.2, 1.1, 1.1, 1.1],
            autoFit: false
          }});
          const stamp = new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-");
          pptx.writeFile({{ fileName: "audit-plan-status-" + stamp + ".pptx" }});
        }});
      }}
      if (planUploadBtn && planUploadFile) {{
        planUploadBtn.addEventListener("click", function () {{
          try {{ planUploadFile.click(); }} catch (_pc) {{}}
        }});
      }}
      if (planUploadFile) {{
        planUploadFile.addEventListener("change", function () {{
          const f = planUploadFile.files && planUploadFile.files[0];
          const badTypeMsg = ui.planUploadBadType || "Unsupported file type.";
          const noRowsMsg = ui.planUploadNoRows || "No plan rows could be read from this file.";
          const needXlsxMsg = ui.planUploadNeedXlsx || "Excel import is unavailable (SheetJS did not load).";
          const needJszipMsg = ui.planUploadNeedJszip || "PowerPoint import is unavailable (JSZip did not load).";
          const pptxFailMsg = ui.planUploadPptxFail || "Could not read the PowerPoint table from this file.";
          function warn(msg) {{
            try {{ window.alert(String(msg || "")); }} catch (_a) {{}}
          }}
          function resetPlanUploadInput() {{
            try {{ planUploadFile.value = ""; }} catch (_v1) {{}}
          }}
          function readBlobAsText(blob, onOk, onErr) {{
            if (blob && typeof blob.text === "function") {{
              blob.text().then(function (t) {{ onOk(String(t != null ? t : "")); }}).catch(function () {{ if (onErr) onErr(); }});
              return;
            }}
            readBlobAsArrayBuffer(blob, function (ab) {{
              try {{
                const td = new TextDecoder("utf-8");
                onOk(td.decode(ab));
              }} catch (_e0) {{
                if (onErr) onErr();
              }}
            }}, onErr);
          }}
          function readBlobAsArrayBuffer(blob, onOk, onErr) {{
            if (blob && typeof blob.arrayBuffer === "function") {{
              blob.arrayBuffer().then(function (ab) {{ onOk(ab); }}).catch(function () {{ if (onErr) onErr(); }});
              return;
            }}
            if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function" || typeof fetch !== "function") {{
              if (onErr) onErr();
              return;
            }}
            let u = "";
            try {{
              u = URL.createObjectURL(blob);
            }} catch (_u0) {{
              if (onErr) onErr();
              return;
            }}
            fetch(u)
              .then(function (r) {{ return r.arrayBuffer(); }})
              .then(function (ab) {{
                try {{ URL.revokeObjectURL(u); }} catch (_r0) {{}}
                onOk(ab);
              }})
              .catch(function () {{
                try {{ URL.revokeObjectURL(u); }} catch (_r1) {{}}
                if (onErr) onErr();
              }});
          }}
          if (!f) {{
            resetPlanUploadInput();
            return;
          }}
          const name = String(f.name || "").toLowerCase();
          if (name.endsWith(".csv")) {{
            readBlobAsText(
              f,
              function (txt) {{
                try {{
                  const lines = String(txt || "").split(/\\r?\\n/).filter(function (x) {{ return x.trim() !== ""; }});
                  if (!lines.length) {{
                    warn(noRowsMsg);
                    return;
                  }}
                  const splitCsv = function (line) {{
                    const out = [];
                    let cur = "";
                    let inQ = false;
                    for (let i = 0; i < line.length; i++) {{
                      const ch = line[i];
                      if (ch === '"' && line[i + 1] === '"' && inQ) {{ cur += '"'; i++; continue; }}
                      if (ch === '"') {{ inQ = !inQ; continue; }}
                      if (ch === "," && !inQ) {{ out.push(cur); cur = ""; continue; }}
                      cur += ch;
                    }}
                    out.push(cur);
                    return out;
                  }};
                  const hdr = splitCsv(lines[0]);
                  const rows = lines.slice(1).map(function (ln) {{
                    const vals = splitCsv(ln);
                    const rec = {{}};
                    hdr.forEach(function (h, i) {{ rec[h] = vals[i] || ""; }});
                    return rec;
                  }});
                  if (!fillPlanFromRecords(rows)) warn(noRowsMsg);
                }} finally {{
                  resetPlanUploadInput();
                }}
              }},
              function () {{ warn(noRowsMsg); resetPlanUploadInput(); }},
            );
          }} else if (name.endsWith(".xlsx") || name.endsWith(".xls") || name.endsWith(".xlsm")) {{
            readBlobAsArrayBuffer(
              f,
              function (ab) {{
                try {{
                  if (typeof XLSX === "undefined") {{
                    warn(needXlsxMsg);
                    return;
                  }}
                  const data = new Uint8Array(ab);
                  const wb = XLSX.read(data, {{ type: "array" }});
                  const ws = wb.Sheets[wb.SheetNames[0]];
                  const rows = XLSX.utils.sheet_to_json(ws, {{ defval: "" }});
                  if (!fillPlanFromRecords(rows)) warn(noRowsMsg);
                }} finally {{
                  resetPlanUploadInput();
                }}
              }},
              function () {{ warn(noRowsMsg); resetPlanUploadInput(); }},
            );
          }} else if (name.endsWith(".json")) {{
            readBlobAsText(
              f,
              function (txt) {{
                try {{
                  const obj = JSON.parse(String(txt || "[]"));
                  const rows = Array.isArray(obj) ? obj : (Array.isArray(obj.rows) ? obj.rows : []);
                  if (!fillPlanFromRecords(rows)) warn(noRowsMsg);
                }} catch (_e) {{
                  warn(noRowsMsg);
                }} finally {{
                  resetPlanUploadInput();
                }}
              }},
              function () {{ warn(noRowsMsg); resetPlanUploadInput(); }},
            );
          }} else if (name.endsWith(".pptx")) {{
            readBlobAsArrayBuffer(
              f,
              function (ab) {{
                function finishClientParse() {{
                  if (typeof JSZip === "undefined") {{
                    warn(needJszipMsg);
                    resetPlanUploadInput();
                    return;
                  }}
                  parsePptxPlanFile(ab)
                    .then(function (rows) {{
                      if (!fillPlanFromRecords(rows)) warn(noRowsMsg);
                    }})
                    .catch(function (_err) {{
                      warn(pptxFailMsg);
                    }})
                    .finally(function () {{
                      resetPlanUploadInput();
                    }});
                }}
                function tryServerThenClient() {{
                  const url = window.__AI_EXCEL_PLAN_PARSE_URL__;
                  if (!url || typeof url !== "string" || url.indexOf("http") !== 0 || typeof fetch !== "function") {{
                    finishClientParse();
                    return;
                  }}
                  function abToB64(buffer) {{
                    const bytes = new Uint8Array(buffer);
                    const chunk = 0x8000;
                    let bin = "";
                    for (let i = 0; i < bytes.length; i += chunk) {{
                      bin += String.fromCharCode.apply(null, bytes.subarray(i, Math.min(bytes.length, i + chunk)));
                    }}
                    return btoa(bin);
                  }}
                  let b64 = "";
                  try {{ b64 = abToB64(ab); }} catch (_e2) {{
                    finishClientParse();
                    return;
                  }}
                  if (!b64) {{
                    finishClientParse();
                    return;
                  }}
                  fetch(url, {{
                    method: "POST",
                    headers: {{ "Content-Type": "application/json" }},
                    body: JSON.stringify({{ pptx_b64: b64 }}),
                  }})
                    .then(function (resp) {{
                      return resp.json().then(function (j) {{
                        return {{ ok: resp.ok, j: j }};
                      }}).catch(function () {{ return {{ ok: false, j: null }}; }});
                    }})
                    .then(function (o) {{
                      if (o && o.j && o.j.ok === true && Array.isArray(o.j.rows) && fillPlanFromRecords(o.j.rows)) {{
                        resetPlanUploadInput();
                        return;
                      }}
                      finishClientParse();
                    }})
                    .catch(function () {{
                      finishClientParse();
                    }});
                }}
                tryServerThenClient();
              }},
              function () {{
                warn(pptxFailMsg);
                resetPlanUploadInput();
              }},
            );
          }} else {{
            warn(badTypeMsg);
            resetPlanUploadInput();
          }}
        }});
      }}
      if (revisedDateWrap && revisedDateLabel && revisedDateInput) {{
        revisedDateLabel.textContent = ui.obsRevisedDateLabel || "Revised date";
        if (hasAgingDateSource) {{
          const now = new Date();
          revisedDateVal = formatIsoDate(new Date(now.getFullYear(), now.getMonth(), now.getDate()));
          revisedDateInput.value = revisedDateVal;
          revisedDateInput.setAttribute("inputmode", "none");
          revisedDateWrap.style.display = "inline-flex";
          const openRevisedPicker = function () {{
            revisedDateInput.focus();
            if (typeof revisedDateInput.showPicker === "function") {{
              try {{ revisedDateInput.showPicker(); }} catch (_e) {{}}
            }}
          }};
          revisedDateWrap.addEventListener("click", function (ev) {{
            if (ev.target === revisedDateInput) return;
            openRevisedPicker();
          }});
          revisedDateInput.addEventListener("focus", function () {{
            if (typeof revisedDateInput.showPicker === "function") {{
              try {{ revisedDateInput.showPicker(); }} catch (_e) {{}}
            }}
          }});
          revisedDateInput.addEventListener("keydown", function (ev) {{
            if (ev.key === "Tab" || ev.key === "Shift" || ev.key === "Escape") return;
            ev.preventDefault();
            if (ev.key === "Enter" || ev.key === " ") openRevisedPicker();
          }});
          revisedDateInput.addEventListener("change", function () {{
            revisedDateVal = revisedDateInput.value || null;
            aoRefresh();
            if ((agingCb && agingCb.checked) || (agingRevisedCb && agingRevisedCb.checked)) renderAgingMatrix(lastAgingRows);
            else syncAgingPanelTitle();
          }});
        }} else {{
          revisedDateWrap.style.display = "none";
        }}
        syncAgingPanelTitle();
      }}

      /** Clear audit toolbar multi-selects; none selected means no filter (same as all values). */
      function resetAuditFilterSelectsToNone() {{
        brandCompanyFilterReopen = false;
        dims.forEach(function (dim, i) {{
          if (dim.key === "y") return;
          const el = auditDimFilterSelectEl(i);
          if (!el || !el.options) return;
          for (let j = 0; j < el.options.length; j++) el.options[j].selected = false;
        }});
      }}
      function aoRowsForYearStrip() {{
        const rows = AO.rows || [];
        const rules = [];
        dims.forEach(function (dim, i) {{
          if (dim.key === "y") return;
          const el = auditDimFilterSelectEl(i);
          if (!el || !el.options || el.options.length === 0) return;
          const picked = Array.from(el.selectedOptions || []).map(function (o) {{ return o.value; }});
          if (!picked.length) return;
          if (picked.length >= el.options.length) return;
          rules.push({{ k: dim.key, vals: picked }});
        }});
        return rows.filter(function (r) {{
          if (!aoRowIsUsable(r)) return false;
          for (let j = 0; j < rules.length; j++) {{
            const dk = rules[j].k;
            let ok = false;
            for (let k = 0; k < rules[j].vals.length; k++) {{
              if (auditToolbarDimMatch(dk, r[dk], rules[j].vals[k])) {{ ok = true; break; }}
            }}
            if (!ok) return false;
          }}
          return true;
        }});
      }}
      function shortlistToolbarSelectionActive() {{
        let active = false;
        dims.forEach(function (dim, i) {{
          if (active) return;
          if (!(dim && (dim.key === "c" || dim.key === "d"))) return;
          const el = auditDimFilterSelectEl(i);
          if (!el || !el.options || el.options.length === 0) return;
          const picked = Array.from(el.selectedOptions || []).map(function (o) {{ return o.value; }});
          if (picked.length > 0 && picked.length < el.options.length) active = true;
        }});
        return active;
      }}

      function aoFilteredRows() {{
        let out = aoRowsForYearStrip();
        if (activeAuditYears.size > 0) {{
          out = out.filter(function (r) {{
            const yk = ffCellKey(r.y);
            const yl = yk === "" ? (ui.statusBlank || "(blank)") : yk;
            return activeAuditYears.has(yl);
          }});
        }}
        return out;
      }}

      function aoStatusSortKey(name, blankLabel) {{
        if (name === blankLabel) return 999;
        const t = iaStatusColorKey(name);
        const order = ["open due", "open not due", "closed", "open", "in progress"];
        const idx = order.indexOf(t);
        return idx === -1 ? 50 : idx;
      }}
      const blankLabel = ui.statusBlank || "(blank)";
      function resolveObsTypeOrder() {{
        if (obsTypeOrderResolved !== null) return obsTypeOrderResolved;
        if (AO.obs_type_order && AO.obs_type_order.length) {{
          obsTypeOrderResolved = AO.obs_type_order.slice();
          return obsTypeOrderResolved;
        }}
        const s = new Set();
        (AO.rows || []).forEach(function (r) {{
          const ok = ffCellKey(r.ot);
          if (ok !== "") s.add(ok);
        }});
        obsTypeOrderResolved = Array.from(s).sort(function (a, b) {{
          return String(a).localeCompare(String(b));
        }});
        return obsTypeOrderResolved;
      }}
      const iaBaseLabels = (function () {{
        const s = new Set();
        (AO.rows || []).forEach(function (r) {{
          const k = ffCellKey(r.ia);
          const label = k === "" ? blankLabel : k;
          s.add(label);
        }});
        const arr = Array.from(s);
        arr.sort(function (a, b) {{
          const sa = aoStatusSortKey(a, blankLabel);
          const sb = aoStatusSortKey(b, blankLabel);
          if (sa !== sb) return sa - sb;
          return String(a).localeCompare(String(b));
        }});
        return arr;
      }})();
      function getOpenDueIaLabelSet() {{
        const want = {{ "open due": true, "open not due": true, "open": true, "in progress": true }};
        const out = [];
        for (let i = 0; i < iaBaseLabels.length; i++) {{
          const lab = iaBaseLabels[i];
          if (lab === blankLabel) continue;
          const n = iaStatusColorKey(lab);
          if (want[n]) out.push(lab);
        }}
        return out;
      }}
      function openPairIaMatchesSelection() {{
        const pair = getOpenDueIaLabelSet();
        if (!pair.length) return false;
        if (activeIaLabels.size !== pair.length) return false;
        for (let i = 0; i < pair.length; i++) {{
          if (!activeIaLabels.has(pair[i])) return false;
        }}
        return true;
      }}

      function iaSelectionActive() {{
        return activeIaLabels.size > 0;
      }}
      function rowIaLabel(r, bl) {{
        const ik = ffCellKey(r.ia);
        return ik === "" ? bl : ik;
      }}
      function rowInIaSelection(r, bl) {{
        if (!iaSelectionActive()) return true;
        return activeIaLabels.has(rowIaLabel(r, bl));
      }}
      function rowIsClosedIa(r, bl) {{
        return normAuditColorKey(rowIaLabel(r, bl)) === "closed";
      }}

      function ratingKeyFromRow(r) {{
        return ffCellKey(r.rt).toLowerCase();
      }}
      function rowMatchesRatingSelection(r) {{
        if (activeRatingValues.size === 0) return true;
        return activeRatingValues.has(ratingKeyFromRow(r));
      }}
      function rowMatchesObsTypeSelection(r, bl) {{
        if (activeObsTypeLabels.size === 0) return true;
        const ok = ffCellKey(r.ot);
        const olab = ok === "" ? bl : ok;
        return activeObsTypeLabels.has(olab);
      }}

      function normalizeObsCheckedIds(fr2list) {{
        if (obsCheckedIds === null) return;
        if (obsCheckedIds.size === 0) return;
        const valid = new Set(fr2list.map(function (x) {{ return x._idx; }}));
        obsCheckedIds = new Set(Array.from(obsCheckedIds).filter(function (id) {{ return valid.has(id); }}));
        if (obsCheckedIds.size === 0) {{
          obsCheckedIds = null;
          return;
        }}
        if (fr2list.length === 0) {{
          obsCheckedIds = null;
          return;
        }}
        if (obsCheckedIds.size === fr2list.length) {{
          let allOn = true;
          for (let z = 0; z < fr2list.length; z++) {{
            if (!obsCheckedIds.has(fr2list[z]._idx)) {{ allOn = false; break; }}
          }}
          if (allOn) obsCheckedIds = null;
        }}
      }}
      function sliceRowsForObsCheck(rows) {{
        if (obsCheckedIds === null) return rows;
        return rows.filter(function (r) {{
          return r._idx != null && obsCheckedIds.has(r._idx);
        }});
      }}

      function aoSliceForObsTypes(baseFr, bl) {{
        let x = baseFr.filter(function (r) {{ return rowInIaSelection(r, bl); }});
        if (activeRatingValues.size > 0) {{
          x = x.filter(function (r) {{ return rowMatchesRatingSelection(r); }});
        }}
        return x;
      }}

      let auditPieIa = null;
      let auditPieYear = null;
      let auditPieRating = null;
      let auditPieObs = null;

      function resizeObsPieCanvas(entryCount) {{
        const wrap = document.querySelector(".audit-pie-card--obs .audit-pie-canvas-wrap");
        if (!wrap) return;
        const n = Math.max(1, Number(entryCount) || 1);
        const h = Math.min(420, Math.max(280, 240 + Math.max(0, n - 3) * 22));
        wrap.style.height = h + "px";
        wrap.style.minHeight = h + "px";
        if (auditPieObs) auditPieObs.resize();
      }}

      const auditPalette = {{
        "very low": "#92D050",
        "low": "#70AD47",
        "medium": "#FFC000",
        "meduim": "#FFC000",
        "high": "#FF3300",
        "critical": "#C00000",
        "open not due": "#FFC000",
        "open due": "#FF3300",
        "open": "#FF3300",
        "in progress": "#FFC000",
        "in-progress": "#FFC000",
        "closed": "#70AD47"
      }};
      function normAuditColorKey(v) {{
        return String(v == null ? "" : v).trim().toLowerCase().replace(/\\s+/g, " ");
      }}
      function iaStatusColorKey(label) {{
        const k = normAuditColorKey(label);
        if (k === "open") return "open due";
        if (k === "in progress" || k === "in-progress") return "open not due";
        return k;
      }}
      function iaStatusDisplayLabel(label, bl) {{
        if (label === bl) return label;
        const k = normAuditColorKey(label);
        const map = {{
          "open due": "Open Due",
          "open not due": "Open Not Due",
          "closed": "Closed",
          "open": "Open Due",
          "in progress": "Open Not Due",
          "in-progress": "Open Not Due",
        }};
        return map[k] || label;
      }}
      function auditColorForLabel(label, fallbackHue) {{
        const k = iaStatusColorKey(label);
        if (Object.prototype.hasOwnProperty.call(auditPalette, k)) return auditPalette[k];
        const nk = normAuditColorKey(label);
        if (Object.prototype.hasOwnProperty.call(auditPalette, nk)) return auditPalette[nk];
        return h(fallbackHue, 72, 56, 0.9);
      }}
      /** Pronounced green gradient for Observation Type only (left = darkest). */
      function obsTypeGradientAt(i, n) {{
        if (n <= 0) return h(148, 72, 36, 0.94);
        const t = n === 1 ? 0 : i / (n - 1);
        const hue = 150 - t * 10;
        const sat = 78 - t * 36;
        const light = 22 + t * 52;
        return h(hue, sat, light, 0.94);
      }}
      function obsTypeGradientColor(label, orderedKeys) {{
        const gradOrder = orderedKeys.slice();
        const n = gradOrder.length;
        let idx = gradOrder.indexOf(label);
        if (idx < 0) idx = Math.max(0, orderedKeys.indexOf(label));
        return obsTypeGradientAt(idx >= 0 ? idx : 0, n);
      }}
      /** Gray gradient for Audit Year (earliest year = lightest, latest = darkest). */
      function auditYearGradientAt(i, n) {{
        if (n <= 0) return h(220, 6, 32, 0.94);
        const t = n === 1 ? 0 : i / (n - 1);
        const sat = 5 + t * 4;
        const light = 88 - t * 56;
        return h(220, sat, light, 0.94);
      }}
      function auditYearGradientColor(label, orderedYearKeys) {{
        const keys = orderedYearKeys.slice().sort(function (a, b) {{
          return String(a).localeCompare(String(b), undefined, {{ numeric: true, sensitivity: "base" }});
        }});
        const n = keys.length;
        const idx = keys.indexOf(label);
        const i = idx >= 0 ? idx : 0;
        return auditYearGradientAt(i, n);
      }}
      function auditMetricFillFromColor(colorCss) {{
        const raw = String(colorCss || "").trim();
        const m = raw.match(/^#?([0-9a-f]{{6}})$/i);
        if (m) return "#" + m[1].toLowerCase();
        return raw;
      }}
      function auditMetricBorderFromColor(colorCss) {{
        const raw = String(colorCss || "").trim();
        const m = raw.match(/^#?([0-9a-f]{{6}})$/i);
        if (m) {{
          const n = m[1];
          const r = parseInt(n.slice(0, 2), 16);
          const g = parseInt(n.slice(2, 4), 16);
          const b = parseInt(n.slice(4, 6), 16);
          const dr = Math.max(0, Math.min(255, Math.round(r * 0.68)));
          const dg = Math.max(0, Math.min(255, Math.round(g * 0.68)));
          const db = Math.max(0, Math.min(255, Math.round(b * 0.68)));
          const hx = function (x) {{ return x.toString(16).padStart(2, "0"); }};
          return "#" + hx(dr) + hx(dg) + hx(db);
        }}
        return "#94a3b8";
      }}
      function auditMetricFgFromColor(colorCss) {{
        const raw = String(colorCss || "").trim();
        const m = raw.match(/^#?([0-9a-f]{{6}})$/i);
        if (!m) return "#0f172a";
        const n = m[1];
        const r = parseInt(n.slice(0, 2), 16) / 255;
        const g = parseInt(n.slice(2, 4), 16) / 255;
        const b = parseInt(n.slice(4, 6), 16) / 255;
        const L = 0.2126 * r + 0.7152 * g + 0.0722 * b;
        return L > 0.62 ? "#111827" : "#ffffff";
      }}
      function applyFlatMetricSurface(el, colorCss) {{
        if (!el) return;
        const base = colorCss;
        el.style.background = auditMetricFillFromColor(base);
        el.style.borderColor = auditMetricBorderFromColor(base);
        el.style.color = auditMetricFgFromColor(base);
      }}

      function ensureAuditPies() {{
        const cIa = document.getElementById("audit-pie-ia-status");
        const cYr = document.getElementById("audit-pie-audit-year");
        const cRt = document.getElementById("audit-pie-rating");
        const cOt = document.getElementById("audit-pie-obs-type");
        if (!cIa || !cYr || !cRt || !cOt) return;
        const mkOpts = function (asDoughnut) {{
          const o = {{
            maintainAspectRatio: false,
            layout: {{ padding: {{ bottom: 4 }} }},
            plugins: {{
              legend: {{
                position: "bottom",
                labels: {{
                  color: "#334155",
                  padding: 12,
                  boxWidth: 10,
                  usePointStyle: true,
                  pointStyle: "circle",
                  font: {{ size: 10, weight: "500" }}
                }}
              }},
              tooltip: {{
                callbacks: {{
                  label: function (ctx) {{
                    const v = ctx.parsed;
                    const arr = ctx.dataset.data;
                    let sum = 0;
                    for (let t = 0; t < arr.length; t++) sum += Number(arr[t]) || 0;
                    const pct = sum ? Math.round((v / sum) * 1000) / 10 : 0;
                    return ctx.label + ": " + v + " (" + pct + "%)";
                  }}
                }}
              }}
            }}
          }};
          if (asDoughnut) o.cutout = "56%";
          return o;
        }};
        const mkObsBarOpts = function () {{
          return {{
            maintainAspectRatio: false,
            layout: {{
              autoPadding: false,
              padding: {{ top: 8, bottom: 2, left: 4, right: 6 }},
            }},
            plugins: {{
              legend: {{ display: false }},
              tooltip: {{
                callbacks: {{
                  label: function (ctx) {{
                    const v = Number(ctx.parsed.y) || 0;
                    let sum = 0;
                    const arr = (ctx.dataset && Array.isArray(ctx.dataset.data)) ? ctx.dataset.data : [];
                    for (let i = 0; i < arr.length; i++) sum += Number(arr[i]) || 0;
                    return (ctx.label ? ctx.label + ": " : "") + v + " (" + chartPctStr(v, sum) + ")";
                  }}
                }}
              }}
            }},
            scales: {{
              x: {{
                grid: {{ display: false }},
                border: {{ display: false }},
                ticks: {{
                  color: "#334155",
                  autoSkip: false,
                  maxRotation: 35,
                  minRotation: 0,
                  padding: 4,
                }}
              }},
              y: {{
                beginAtZero: true,
                grace: "12%",
                border: {{ display: false }},
                grid: {{ color: "rgba(15,23,42,0.06)", drawBorder: false }},
                ticks: {{
                  color: "#334155",
                  padding: 4,
                  precision: 0,
                }}
              }}
            }}
          }};
        }};
        const mkDataset = function () {{
          return {{
            data: [],
            backgroundColor: [],
            borderWidth: 2,
            borderColor: "rgba(15, 23, 42, 0.92)",
            hoverOffset: 10
          }};
        }};
        if (!auditPieIa) {{
          auditPieIa = new Chart(cIa, {{
            type: "doughnut",
            data: {{ labels: [], datasets: [mkDataset()] }},
            options: mkOpts(true)
          }});
        }}
        if (!auditPieYear) {{
          auditPieYear = new Chart(cYr, {{
            type: "pie",
            data: {{ labels: [], datasets: [mkDataset()] }},
            options: mkOpts(false)
          }});
        }}
        if (!auditPieRating) {{
          auditPieRating = new Chart(cRt, {{
            type: "doughnut",
            data: {{ labels: [], datasets: [mkDataset()] }},
            options: mkOpts(true)
          }});
        }}
        if (!auditPieObs) {{
          auditPieObs = new Chart(cOt, {{
            type: "bar",
            data: {{ labels: [], datasets: [] }},
            options: mkObsBarOpts()
          }});
        }}
      }}

      function updateAuditPies(entriesIa, entriesYear, entriesRating, entriesObs, blankLabel) {{
        ensureAuditPies();
        const emptyLbl = ui.auditPieEmpty || "No data";
        const naLbl = ui.auditPieUnavailable || "N/A";
        const pieEmpty = function (chart, label) {{
          if (!chart) return;
          chart.data.labels = [label];
          chart.data.datasets[0].data = [1];
          chart.data.datasets[0].backgroundColor = ["rgba(100, 116, 139, 0.42)"];
          chart.update("none");
        }};
        const applyEntries = function (chart, entries, hue0) {{
          if (!chart) return;
          if (!entries.length) {{
            pieEmpty(chart, emptyLbl);
            return;
          }}
          chart.data.labels = entries.map(function (p) {{ return p[0]; }});
          chart.data.datasets[0].data = entries.map(function (p) {{ return p[1]; }});
          chart.data.datasets[0].backgroundColor = entries.map(function (p, i) {{
            const c = auditColorForLabel(p[0], hue0 + i * 13);
            return c;
          }});
          chart.update("none");
        }};
        const applyObsEntries = function (chart, entries, hue0) {{
          if (!chart) return;
          if (!entries.length) {{
            chart.data.labels = [emptyLbl];
            chart.data.datasets = [{{
              label: emptyLbl,
              data: [1],
              backgroundColor: "rgba(100, 116, 139, 0.42)",
              borderColor: "rgba(100, 116, 139, 0.75)",
              borderWidth: 1,
              borderSkipped: "bottom",
              borderRadius: {{ topLeft: 6, topRight: 6 }},
              barThickness: 22,
              clip: false,
            }}];
            resizeObsPieCanvas(1);
            chart.update("none");
            return;
          }}
          chart.data.labels = entries.map(function (p) {{ return p[0]; }});
          const obsKeyOrder = entries.map(function (p) {{ return p[0]; }});
          chart.data.datasets = [{{
            label: ui.auditPieObsTitle || "Observation type",
            data: entries.map(function (p) {{ return p[1]; }}),
            backgroundColor: entries.map(function (p) {{ return obsTypeGradientColor(p[0], obsKeyOrder); }}),
            borderColor: "rgba(15, 23, 42, 0.9)",
            borderWidth: 1.5,
            borderSkipped: "bottom",
            borderRadius: {{ topLeft: 6, topRight: 6 }},
            barThickness: 22,
            clip: false,
          }}];
          resizeObsPieCanvas(entries.length);
          chart.update("none");
        }};
        if (auditPieIa) {{
          applyEntries(auditPieIa, entriesIa, T.h1);
        }}
        if (auditPieYear) {{
          if (!entriesYear.length) {{
            pieEmpty(auditPieYear, emptyLbl);
          }} else {{
            auditPieYear.data.labels = entriesYear.map(function (p) {{ return p[0]; }});
            auditPieYear.data.datasets[0].data = entriesYear.map(function (p) {{ return p[1]; }});
            const yearKeyOrder = entriesYear.map(function (p) {{ return p[0]; }});
            auditPieYear.data.datasets[0].backgroundColor = entriesYear.map(function (p) {{
              return auditYearGradientColor(p[0], yearKeyOrder);
            }});
            auditPieYear.update("none");
          }}
        }}
        if (auditPieRating) {{
          if (!AO.has_rating) {{
            pieEmpty(auditPieRating, naLbl);
          }} else {{
            applyEntries(auditPieRating, entriesRating, T.h2);
          }}
        }}
        if (auditPieObs) {{
          if (!AO.has_observation_type) {{
            applyObsEntries(auditPieObs, [], T.h3);
          }} else {{
            applyObsEntries(auditPieObs, entriesObs, T.h3);
          }}
        }}
      }}

      function buildRatingButtons() {{
        if (!ratingBtnHost || !ratingsBox) return;
        if (!AO.has_rating || !(AO.rating_types && AO.rating_types.length)) {{
          ratingsBox.style.display = "none";
          return;
        }}
        ratingsBox.style.display = "";
        ratingBtnHost.innerHTML = "";
        (AO.rating_types || []).forEach(function (rt) {{
          const b = document.createElement("button");
          b.type = "button";
          b.className = "audit-rating-btn";
          b.setAttribute("data-rating", rt.value);
          const btnCol = auditColorForLabel(rt.value, T.h2);
          applyFlatMetricSurface(b, btnCol);
          b.style.boxShadow = "none";
          const labSp = document.createElement("span");
          labSp.className = "audit-rating-lbl";
          const numSp = document.createElement("span");
          numSp.className = "audit-rating-n";
          labSp.textContent = rt.value;
          numSp.textContent = "0";
          b.appendChild(labSp);
          b.appendChild(numSp);
          ratingBtnHost.appendChild(b);
          const rKey = String(rt.value).toLowerCase();
          b.setAttribute("aria-pressed", activeRatingValues.has(rKey) ? "true" : "false");
          b.addEventListener("click", function () {{
            if (activeRatingValues.has(rKey)) activeRatingValues.delete(rKey);
            else activeRatingValues.add(rKey);
            obsCheckedIds = null;
            aoRefresh();
          }});
        }});
        const totRg = document.createElement("div");
        totRg.id = "audit-rating-total-row";
        totRg.className = "audit-rating-total-pill";
        const tlb = document.createElement("span");
        tlb.className = "audit-rating-total-lbl";
        const tnum = document.createElement("span");
        tnum.className = "audit-rating-total-n";
        totRg.appendChild(tlb);
        totRg.appendChild(tnum);
        ratingBtnHost.appendChild(totRg);
      }}

      function companyFilterSelectEl() {{
        const branded = document.getElementById("brand-filter-co");
        if (branded) return branded;
        if (companyIdx < 0) return null;
        return document.getElementById("ao-sel-" + companyIdx);
      }}
      function subcompanyFilterSelectEl() {{
        const branded = document.getElementById("brand-filter-sc");
        if (branded) return branded;
        if (subcompanyIdx < 0) return null;
        return document.getElementById("ao-sel-" + subcompanyIdx);
      }}
      function auditDimFilterSelectEl(i) {{
        if (i === companyIdx) {{
          const co = companyFilterSelectEl();
          if (co) return co;
        }}
        if (i === subcompanyIdx) {{
          const sc = subcompanyFilterSelectEl();
          if (sc) return sc;
        }}
        return document.getElementById("ao-sel-" + i);
      }}
      function brandFilterSelectionCount() {{
        let n = 0;
        const s1 = companyFilterSelectEl();
        if (s1 && s1.selectedOptions) {{
          n += Array.from(s1.selectedOptions).filter(function (o) {{
            return String(o.textContent || o.value || "").trim() !== "";
          }}).length;
        }}
        const s2 = subcompanyFilterSelectEl();
        if (s2 && s2.selectedOptions) {{
          n += Array.from(s2.selectedOptions).filter(function (o) {{
            return String(o.textContent || o.value || "").trim() !== "";
          }}).length;
        }}
        return n;
      }}
      function brandFilterSelectionCountForHost() {{
        if (brandBoxSubcompanyOnly) {{
          const s2 = subcompanyFilterSelectEl();
          if (!s2 || !s2.selectedOptions) return 0;
          return Array.from(s2.selectedOptions).filter(function (o) {{
            return String(o.textContent || o.value || "").trim() !== "";
          }}).length;
        }}
        return brandFilterSelectionCount();
      }}
      function normLogoKey(label) {{
        return String(label || "")
          .trim()
          .toLowerCase()
          .replace(/[^\\w\\s\u0600-\u06ff.-]+/g, "")
          .replace(/\\s+/g, " ")
          .trim();
      }}
      function lookupBrandLogoEntry(label, mapObj) {{
        const raw = String(label || "").trim();
        if (!raw || !mapObj) return "";
        if (mapObj[raw]) return mapObj[raw];
        const nk = normLogoKey(raw);
        return nk && mapObj[nk] ? mapObj[nk] : "";
      }}
      function brandLogoCatalogPayload() {{
        return payload.brand_logo_catalog || {{}};
      }}
      function brandLogoPickFromSelect(sel) {{
        if (!sel || !sel.selectedOptions) return "";
        const picked = Array.from(sel.selectedOptions)
          .map(function (o) {{ return String(o.textContent || o.value || "").trim(); }})
          .filter(function (x) {{ return x !== ""; }})
          .sort(function (a, b) {{ return String(a).localeCompare(String(b)); }});
        return picked.length ? picked[0] : "";
      }}
      function brandLogoPickAllFromSelect(sel) {{
        if (!sel || !sel.selectedOptions) return [];
        return Array.from(sel.selectedOptions)
          .map(function (o) {{ return String(o.textContent || o.value || "").trim(); }})
          .filter(function (x) {{ return x !== ""; }})
          .sort(function (a, b) {{ return String(a).localeCompare(String(b)); }});
      }}
      function brandLogoInferCompanyFromRows() {{
        if (!AO || !Array.isArray(AO.rows)) return "";
        const cos = Array.from(
          new Set(
            AO.rows
              .map(function (r) {{ return String((r && r.co) != null ? r.co : "").trim(); }})
              .filter(function (v) {{ return v !== ""; }})
          )
        );
        if (cos.length === 1) return cos[0];
        return "";
      }}
      function brandLogoInferSubcompanyFromRows(companyLabel) {{
        if (!AO || !Array.isArray(AO.rows)) return "";
        const coKey = normLogoKey(companyLabel);
        const subs = Array.from(
          new Set(
            AO.rows
              .filter(function (r) {{
                if (!companyLabel) return true;
                return normLogoKey(String((r && r.co) != null ? r.co : "")) === coKey;
              }})
              .map(function (r) {{ return String((r && r.sco) != null ? r.sco : "").trim(); }})
              .filter(function (v) {{ return v !== ""; }})
          )
        );
        if (subs.length === 1) return subs[0];
        return "";
      }}
      function brandLogoCompositeUri(coExact, scExact, coKey, scKey) {{
        const subcompanies = (brandLogoCatalogPayload().subcompanies || {{}});
        if (coExact && scExact) {{
          if (subcompanies[coExact + "|" + scExact]) return subcompanies[coExact + "|" + scExact];
          if (coKey && scKey && subcompanies[coKey + "|" + scKey]) return subcompanies[coKey + "|" + scKey];
        }}
        if (scKey || scExact) {{
          const scOnly = Object.keys(subcompanies).find(function (k) {{
            return k.endsWith("|" + scExact) || (scKey && k.endsWith("|" + scKey));
          }});
          if (scOnly) return subcompanies[scOnly];
        }}
        return "";
      }}
      function brandLogoFromActiveFilters() {{
        const companies = (brandLogoCatalogPayload().companies || {{}});
        if (!companies || !Object.keys(companies).length) return "";
        function hit(label) {{
          return lookupBrandLogoEntry(label, companies);
        }}
        const scSel = subcompanyFilterSelectEl();
        if (scSel && scSel.selectedOptions && scSel.options && scSel.options.length) {{
          const picked = brandLogoPickAllFromSelect(scSel);
          if (picked.length > 0 && picked.length < scSel.options.length) {{
            for (let i = 0; i < picked.length; i++) {{
              const uri = hit(picked[i]);
              if (uri) return uri;
            }}
          }}
        }}
        const coSel = companyFilterSelectEl();
        if (coSel && coSel.selectedOptions && coSel.options && coSel.options.length) {{
          const pickedCo = brandLogoPickAllFromSelect(coSel);
          if (pickedCo.length > 0 && pickedCo.length < coSel.options.length) {{
            for (let j = 0; j < pickedCo.length; j++) {{
              const uriCo = hit(pickedCo[j]);
              if (uriCo) return uriCo;
            }}
          }}
        }}
        let rows = [];
        try {{
          rows = typeof aoRowsForYearStrip === "function" ? aoRowsForYearStrip() : [];
        }} catch (_rows) {{
          rows = [];
        }}
        if (!rows.length) return "";
        const subs = Array.from(
          new Set(
            rows
              .map(function (r) {{ return String((r && r.sco) != null ? r.sco : "").trim(); }})
              .filter(function (v) {{ return v !== ""; }})
          )
        );
        if (subs.length === 1) {{
          const uriSub = hit(subs[0]);
          if (uriSub) return uriSub;
        }}
        const cos = Array.from(
          new Set(
            rows
              .map(function (r) {{ return String((r && r.co) != null ? r.co : "").trim(); }})
              .filter(function (v) {{ return v !== ""; }})
          )
        );
        if (cos.length === 1) {{
          const uriCoOnly = hit(cos[0]);
          if (uriCoOnly) return uriCoOnly;
        }}
        return "";
      }}
      function brandLogoFromVisibleChips() {{
        const companies = (brandLogoCatalogPayload().companies || {{}});
        const chips = document.querySelectorAll(
          "#brand-context-company-names .brand-context-chip:not(.brand-context-chip--muted)"
        );
        for (let i = 0; i < chips.length; i++) {{
          const uri = lookupBrandLogoEntry(String(chips[i].textContent || "").trim(), companies);
          if (uri) return uri;
        }}
        return "";
      }}
      function resolveBrandLogoUri() {{
        const cat = brandLogoCatalogPayload();
        const def = cat.default || "";
        const companies = cat.companies || {{}};
        const activeLogo = brandLogoFromActiveFilters();
        if (activeLogo) return activeLogo;
        const chipLogo = brandLogoFromVisibleChips();
        if (chipLogo) return chipLogo;
        const scSel = subcompanyFilterSelectEl();
        const coSel = companyFilterSelectEl();
        const scPicks = brandLogoPickAllFromSelect(scSel);
        const coPicks = brandLogoPickAllFromSelect(coSel);
        for (let si = 0; si < scPicks.length; si++) {{
          const scHit = lookupBrandLogoEntry(scPicks[si], companies);
          if (scHit) return scHit;
        }}
        for (let ci = 0; ci < coPicks.length; ci++) {{
          const coHit = lookupBrandLogoEntry(coPicks[ci], companies);
          if (coHit) return coHit;
        }}
        if (!scPicks.length && !coPicks.length) {{
          let co = brandLogoPickFromSelect(coSel);
          let sc = brandLogoPickFromSelect(scSel);
          if (!co) co = brandLogoInferCompanyFromRows();
          if (!sc) sc = brandLogoInferSubcompanyFromRows(co);
          const coKey = normLogoKey(co);
          const coExact = String(co || "").trim();
          const scExact = String(sc || "").trim();
          const composite = brandLogoCompositeUri(coExact, scExact, coKey, normLogoKey(sc));
          if (composite) return composite;
          const scLogo = lookupBrandLogoEntry(sc, companies);
          if (scLogo) return scLogo;
          const coLogo = lookupBrandLogoEntry(co, companies);
          if (coLogo) return coLogo;
        }}
        return def || "";
      }}
      function syncBrandLogo() {{
        const img = document.getElementById("brand-logo-img");
        const btn = document.getElementById("brand-logo-reset");
        if (!img) return;
        const uri = resolveBrandLogoUri();
        const fallback = img.getAttribute("data-default-src") || brandLogoCatalogPayload().default || "";
        const next = uri || fallback;
        if (next) {{
          if (img.getAttribute("data-current-logo") !== next) {{
            img.setAttribute("data-current-logo", next);
            img.src = next;
          }}
          if (btn) btn.style.display = "inline-flex";
        }} else if (btn) {{
          btn.style.display = "none";
        }}
      }}
      function syncBrandCompanyFilterHostVisibility() {{
        const host = document.getElementById("brand-company-filter-host");
        if (!host || !host.classList.contains("brand-company-filter-host--visible")) return;
        const n = brandFilterSelectionCountForHost();
        // Keep Subcompany filter pinned beside logo when present.
        const show = hasSubcompanyFilterDim ? true : (n === 0 || brandCompanyFilterReopen);
        host.classList.toggle("brand-company-filter-host--hidden", !show);
        host.classList.toggle(
          "brand-company-filter-host--compact",
          show && n === 0,
        );
      }}
      function syncBrandStripCompanies() {{
        const aside = document.getElementById("brand-context-aside");
        const kicker = document.getElementById("brand-context-kicker");
        const namesHost = document.getElementById("brand-context-company-names");
        const reopenBtn = document.getElementById("brand-company-filter-reopen");
        if (!aside || !kicker || !namesHost) return;
        if (!aside.classList.contains("brand-context-aside--visible")) return;
        const sel = companyFilterSelectEl();
        const scStrip = subcompanyFilterSelectEl();
        namesHost.innerHTML = "";
        function finishBrandStrip() {{
          const coEl = companyFilterSelectEl();
          const scEl = subcompanyFilterSelectEl();
          let nPick;
          let multiCo;
          let multiSc;
          if (brandBoxSubcompanyOnly) {{
            nPick = scEl && scEl.selectedOptions
              ? Array.from(scEl.selectedOptions).filter(function (o) {{
                  return String(o.textContent || o.value || "").trim() !== "";
                }}).length
              : 0;
            multiCo = false;
            multiSc = !!(scEl && scEl.options && scEl.options.length > 1);
          }} else {{
            nPick = brandFilterSelectionCount();
            multiCo = !!(coEl && coEl.options && coEl.options.length > 1);
            multiSc = !!(scEl && scEl.options && scEl.options.length > 1);
          }}
          if (reopenBtn) {{
            reopenBtn.hidden = !(multiCo || multiSc || nPick > 0);
          }}
          syncBrandCompanyFilterHostVisibility();
          syncBrandLogo();
        }}
        if (brandBoxSubcompanyOnly && scStrip && scStrip.options && scStrip.options.length > 0) {{
          kicker.textContent = ui.brandSubcompaniesInFilterTitle || ui.subcompanyLabel || "Subcompanies";
          const spicked2 = Array.from(scStrip.selectedOptions || []).map(function (o) {{ return String(o.textContent || o.value || "").trim(); }}).filter(function (x) {{ return x !== ""; }});
          if (spicked2.length === 0) {{
            const th = document.createElement("span");
            th.className = "brand-context-chip brand-context-chip--muted";
            th.textContent = ui.brandAllSubcompaniesHint || "All subcompanies";
            namesHost.appendChild(th);
            finishBrandStrip();
            return;
          }}
          spicked2.sort(function (a, b) {{ return String(a).localeCompare(String(b)); }});
          for (let si2 = 0; si2 < spicked2.length; si2++) {{
            const sp2 = document.createElement("span");
            sp2.className = "brand-context-chip";
            sp2.textContent = spicked2[si2];
            namesHost.appendChild(sp2);
          }}
          finishBrandStrip();
          return;
        }}
        if ((!sel || !sel.options || sel.options.length === 0) && (!scStrip || !scStrip.options || scStrip.options.length === 0)) {{
          kicker.textContent = ui.brandCompaniesInFilterTitle || ui.companyLabel || "Company";
          const t = document.createElement("span");
          t.textContent = ui.brandNoCompanySelected || "—";
          namesHost.appendChild(t);
          finishBrandStrip();
          return;
        }}
        if (!sel || !sel.options || sel.options.length === 0) {{
          kicker.textContent = ui.brandSubcompaniesInFilterTitle || ui.subcompanyLabel || "Subcompanies";
          const spicked = Array.from(scStrip.selectedOptions || []).map(function (o) {{ return String(o.textContent || o.value || "").trim(); }}).filter(function (x) {{ return x !== ""; }});
          if (spicked.length === 0) {{
            const th = document.createElement("span");
            th.className = "brand-context-chip brand-context-chip--muted";
            th.textContent = ui.brandAllSubcompaniesHint || "All subcompanies (optional filter off)";
            namesHost.appendChild(th);
            finishBrandStrip();
            return;
          }}
          spicked.sort(function (a, b) {{ return String(a).localeCompare(String(b)); }});
          for (let si = 0; si < spicked.length; si++) {{
            const sp = document.createElement("span");
            sp.className = "brand-context-chip";
            sp.textContent = spicked[si];
            namesHost.appendChild(sp);
          }}
          finishBrandStrip();
          return;
        }}
        kicker.textContent = ui.brandCompaniesInFilterTitle || ui.companyLabel || "Company";
        const picked = Array.from(sel.selectedOptions || []).map(function (o) {{ return String(o.textContent || o.value || "").trim(); }}).filter(function (x) {{ return x !== ""; }});
        if (picked.length === 0) {{
          const t = document.createElement("span");
          t.textContent = ui.brandNoCompanySelected || "—";
          namesHost.appendChild(t);
          finishBrandStrip();
          return;
        }}
        picked.sort(function (a, b) {{ return String(a).localeCompare(String(b)); }});
        for (let pi = 0; pi < picked.length; pi++) {{
          const sp = document.createElement("span");
          sp.className = "brand-context-chip";
          sp.textContent = picked[pi];
          namesHost.appendChild(sp);
        }}
        finishBrandStrip();
      }}

      function aoRefresh() {{
        const yearRows = aoRowsForYearStrip();
        const yearCounts = {{}};
        for (let i = 0; i < yearRows.length; i++) {{
          const yk = ffCellKey(yearRows[i].y);
          if (yk === "") continue;
          yearCounts[yk] = (yearCounts[yk] || 0) + 1;
        }}
        const yearKeys = Object.keys(yearCounts).sort(function (a, b) {{
          return String(a).localeCompare(String(b), undefined, {{ numeric: true, sensitivity: "base" }});
        }});
        if (activeAuditYears.size > 0) {{
          const ykOk = new Set(yearKeys);
          activeAuditYears = new Set(Array.from(activeAuditYears).filter(function (y) {{ return ykOk.has(y); }}));
        }}
        if (yearBtnHost && yearBox) {{
          yearBtnHost.innerHTML = "";
          if (!yearKeys.length) {{
            yearBox.style.display = "none";
          }} else {{
            yearBox.style.display = "";
            yearKeys.forEach(function (yk, yi) {{
              const yb = document.createElement("button");
              yb.type = "button";
              yb.className = "audit-rating-btn";
              yb.setAttribute("data-audit-year", yk);
              const yrCol = auditYearGradientColor(yk, yearKeys);
              applyFlatMetricSurface(yb, yrCol);
              yb.style.boxShadow = "none";
              const yLabSp = document.createElement("span");
              yLabSp.className = "audit-rating-lbl";
              const yNumSp = document.createElement("span");
              yNumSp.className = "audit-rating-n";
              yLabSp.textContent = yk;
              yNumSp.textContent = String(yearCounts[yk]);
              yb.appendChild(yLabSp);
              yb.appendChild(yNumSp);
              yb.setAttribute("aria-pressed", activeAuditYears.has(yk) ? "true" : "false");
              yb.classList.toggle("audit-rating-active", activeAuditYears.has(yk));
              yb.addEventListener("click", function () {{
                if (activeAuditYears.has(yk)) activeAuditYears.delete(yk);
                else activeAuditYears.add(yk);
                obsCheckedIds = null;
                aoRefresh();
              }});
              yearBtnHost.appendChild(yb);
            }});
            const totYr = document.createElement("div");
            totYr.id = "audit-year-total-row";
            totYr.className = "audit-rating-total-pill";
            const tly = document.createElement("span");
            tly.className = "audit-rating-total-lbl";
            const tny = document.createElement("span");
            tny.className = "audit-rating-total-n";
            tly.textContent = ui.ratingTypesTotal || "Total";
            tny.textContent = String(
              yearKeys.reduce(function (sum, k) {{ return sum + (yearCounts[k] || 0); }}, 0)
            );
            totYr.appendChild(tly);
            totYr.appendChild(tny);
            yearBtnHost.appendChild(totYr);
          }}
        }}
        const fr = aoFilteredRows();
        if (activeRatingValues.size > 0 && AO.rating_types) {{
          const vk = new Set((AO.rating_types || []).map(function (x) {{ return String(x.value).toLowerCase(); }}));
          activeRatingValues = new Set(Array.from(activeRatingValues).filter(function (k) {{ return vk.has(k); }}));
        }}
        const counts = {{}};
        for (let i = 0; i < fr.length; i++) {{
          const r = fr[i];
          const k = ffCellKey(r.ia);
          const label = k === "" ? blankLabel : k;
          counts[label] = (counts[label] || 0) + 1;
        }}
        const entries = iaBaseLabels.map(function (label) {{
          return [label, counts[label] || 0];
        }});
        let frForRatings = fr.filter(function (r) {{ return rowInIaSelection(r, blankLabel); }});
        const totalVal = iaSelectionActive() ? frForRatings.length : fr.length;
        const tl = document.getElementById("audit-total-label");
        const tv = document.getElementById("audit-total-val");
        const ts = document.getElementById("audit-total-sub");
        if (tl) tl.textContent = ui.totalLabel || "Total";
        if (tv) tv.textContent = String(totalVal);
        if (ts) {{
          if (!iaSelectionActive()) {{
            ts.textContent = ui.totalSubAll || "";
          }} else if (activeIaLabels.size === 1) {{
            const one = Array.from(activeIaLabels)[0];
            ts.textContent = String((ui.totalSubStatus || "").replace(/\\{{status\\}}/g, one));
          }} else {{
            const joined = Array.from(activeIaLabels).sort(function (a, b) {{ return String(a).localeCompare(String(b)); }}).join(", ");
            ts.textContent = String((ui.totalSubStatuses || "").replace(/\\{{statuses\\}}/g, joined));
          }}
        }}
        const auditTotalCard = document.getElementById("audit-total-card");
        if (auditTotalCard) {{
          const openPairOn = openPairIaMatchesSelection();
          auditTotalCard.classList.toggle("audit-tile-active", openPairOn);
          auditTotalCard.setAttribute("aria-pressed", openPairOn ? "true" : "false");
          if (ui.totalCardAria) auditTotalCard.setAttribute("aria-label", ui.totalCardAria);
        }}
        if (tilesHost) {{
          tilesHost.innerHTML = "";
          for (let i = 0; i < entries.length; i++) {{
            const pair = entries[i];
            const tile = document.createElement("div");
            tile.className = "stat-tile audit-ia-tile st-" + (i % 6);
            tile.setAttribute("role", "button");
            tile.setAttribute("aria-pressed", activeIaLabels.has(pair[0]) ? "true" : "false");
            tile.tabIndex = 0;
            const iaCol = auditColorForLabel(pair[0], T.h1);
            applyFlatMetricSurface(tile, iaCol);
            tile.style.boxShadow = "none";
            if (activeIaLabels.has(pair[0])) tile.classList.add("audit-tile-active");
            const lab = document.createElement("span");
            lab.className = "st-label";
            lab.textContent = iaStatusDisplayLabel(pair[0], blankLabel);
            const val = document.createElement("span");
            val.className = "st-val";
            val.textContent = String(pair[1]);
            tile.appendChild(lab);
            tile.appendChild(val);
            tile.addEventListener("click", function () {{
              const lbl = pair[0];
              if (activeIaLabels.has(lbl)) activeIaLabels.delete(lbl);
              else activeIaLabels.add(lbl);
              obsCheckedIds = null;
              aoRefresh();
            }});
            tile.addEventListener("keydown", function (ev) {{
              if (ev.key === "Enter" || ev.key === " ") {{
                ev.preventDefault();
                tile.click();
              }}
            }});
            tilesHost.appendChild(tile);
          }}
        }}
        if (ratingBtnHost) {{
          const btns = ratingBtnHost.querySelectorAll(".audit-rating-btn");
          btns.forEach(function (btn) {{
            const rv = btn.getAttribute("data-rating");
            let c = 0;
            for (let j = 0; j < frForRatings.length; j++) {{
              if (ffCellKey(frForRatings[j].rt).toLowerCase() === String(rv).toLowerCase()) c++;
            }}
            const rtDef = (AO.rating_types || []).find(function (x) {{ return x.value === rv; }});
            const baseLabel = rtDef ? rtDef.label : rv;
            const lblEl = btn.querySelector(".audit-rating-lbl");
            const numEl = btn.querySelector(".audit-rating-n");
            if (lblEl) lblEl.textContent = rtDef ? rtDef.value : rv;
            if (numEl) numEl.textContent = String(c);
            const rk = String(rv).toLowerCase();
            const rOn = activeRatingValues.has(rk);
            btn.classList.toggle("audit-rating-active", rOn);
            btn.setAttribute("aria-pressed", rOn ? "true" : "false");
          }});
          const totRgEl = document.getElementById("audit-rating-total-row");
          if (totRgEl) {{
            const tlbEl = totRgEl.querySelector(".audit-rating-total-lbl");
            const tnumEl = totRgEl.querySelector(".audit-rating-total-n");
            if (tlbEl) tlbEl.textContent = ui.ratingTypesTotal || "Total";
            if (tnumEl) tnumEl.textContent = String(frForRatings.length);
          }}
        }}
        const obsTypesBox = document.getElementById("audit-box-obs-types");
        const obsTypesWrap = document.getElementById("audit-obs-types-row-wrap");
        if (AO.has_observation_type && obsTypeBtnHost && obsTypesBox) {{
          if (obsTypesWrap) obsTypesWrap.style.display = "";
          obsTypesBox.style.display = "";
          let frForObsTypes = fr.filter(function (r) {{ return rowInIaSelection(r, blankLabel); }});
          if (activeRatingValues.size > 0) {{
            frForObsTypes = frForObsTypes.filter(function (r) {{ return rowMatchesRatingSelection(r); }});
          }}
          const otm = {{}};
          for (let i = 0; i < frForObsTypes.length; i++) {{
            const ok = ffCellKey(frForObsTypes[i].ot);
            const olab = ok === "" ? blankLabel : ok;
            otm[olab] = (otm[olab] || 0) + 1;
          }}
          const typeOrder = resolveObsTypeOrder();
          const orderThisPass = typeOrder.length
            ? typeOrder.slice()
            : Object.keys(otm).sort(function (a, b) {{ return String(a).localeCompare(String(b)); }});
          if (activeObsTypeLabels.size > 0) {{
            const okObs = new Set(orderThisPass);
            Object.keys(otm).forEach(function (x) {{ okObs.add(x); }});
            activeObsTypeLabels = new Set(Array.from(activeObsTypeLabels).filter(function (x) {{ return okObs.has(x); }}));
          }}
          function obsTypeBtnFind(host, key) {{
            const nodes = host.querySelectorAll("[data-obs-type]");
            for (let ni = 0; ni < nodes.length; ni++) {{
              if (nodes[ni].getAttribute("data-obs-type") === key) return nodes[ni];
            }}
            return null;
          }}
          if (orderThisPass.length === 0) {{
            obsTypesBox.style.display = "none";
            if (obsTypesWrap) obsTypesWrap.style.display = "none";
          }} else {{
            if (!obsTypeStripInited) {{
              obsTypeStripOrder = orderThisPass.slice();
              obsTypeBtnHost.innerHTML = "";
              obsTypeStripOrder.forEach(function (k) {{
                const b = document.createElement("button");
                b.type = "button";
                b.className = "audit-rating-btn";
                b.setAttribute("data-obs-type", k);
                const otCol = obsTypeGradientColor(k, obsTypeStripOrder);
                applyFlatMetricSurface(b, otCol);
                b.style.boxShadow = "none";
                const labSp = document.createElement("span");
                labSp.className = "audit-rating-lbl";
                const numSp = document.createElement("span");
                numSp.className = "audit-rating-n";
                labSp.textContent = k;
                numSp.textContent = String(otm[k] || 0);
                b.appendChild(labSp);
                b.appendChild(numSp);
                const oOn = activeObsTypeLabels.has(k);
                b.classList.toggle("audit-rating-active", oOn);
                b.setAttribute("aria-pressed", oOn ? "true" : "false");
                b.addEventListener("click", function () {{
                  if (activeObsTypeLabels.has(k)) activeObsTypeLabels.delete(k);
                  else activeObsTypeLabels.add(k);
                  obsCheckedIds = null;
                  aoRefresh();
                }});
                obsTypeBtnHost.appendChild(b);
              }});
              const totOt = document.createElement("div");
              totOt.id = "audit-obs-type-total-row";
              totOt.className = "audit-rating-total-pill";
              const tlo = document.createElement("span");
              tlo.className = "audit-rating-total-lbl";
              const tno = document.createElement("span");
              tno.className = "audit-rating-total-n";
              tlo.textContent = ui.ratingTypesTotal || "Total";
              tno.textContent = String(frForObsTypes.length);
              totOt.appendChild(tlo);
              totOt.appendChild(tno);
              obsTypeBtnHost.appendChild(totOt);
              obsTypeStripInited = true;
            }} else if (obsTypeStripOrder) {{
              obsTypeStripOrder.forEach(function (k) {{
                const b = obsTypeBtnFind(obsTypeBtnHost, k);
                if (!b) return;
                const numSp = b.querySelector(".audit-rating-n");
                if (numSp) numSp.textContent = String(otm[k] || 0);
                const oOn = activeObsTypeLabels.has(k);
                b.classList.toggle("audit-rating-active", oOn);
                b.setAttribute("aria-pressed", oOn ? "true" : "false");
              }});
              const totOtEl = document.getElementById("audit-obs-type-total-row");
              if (totOtEl) {{
                const tno2 = totOtEl.querySelector(".audit-rating-total-n");
                if (tno2) tno2.textContent = String(frForObsTypes.length);
              }}
            }}
          }}
        }} else if (obsTypesBox) {{
          obsTypesBox.style.display = "none";
          if (obsTypesWrap) obsTypesWrap.style.display = "none";
        }}
        if (obsBarTitle) obsBarTitle.textContent = ui.obsListHeading || "";
        let fr2names = fr.filter(function (r) {{ return rowInIaSelection(r, blankLabel); }});
        if (activeRatingValues.size > 0) {{
          fr2names = fr2names.filter(function (r) {{ return rowMatchesRatingSelection(r); }});
        }}
        if (activeObsTypeLabels.size > 0) {{
          fr2names = fr2names.filter(function (r) {{ return rowMatchesObsTypeSelection(r, blankLabel); }});
        }}
        fr2names = fr2names.filter(function (r) {{ return !rowIsClosedIa(r, blankLabel); }});
        lastAgingRows = fr2names.slice();
        normalizeObsCheckedIds(fr2names);
        const rowsIaPieBase = iaSelectionActive() ? frForRatings : fr;
        const rowsIaPieSliced = sliceRowsForObsCheck(rowsIaPieBase);
        const countsIaPie = {{}};
        for (let ip = 0; ip < rowsIaPieSliced.length; ip++) {{
          const r = rowsIaPieSliced[ip];
          const k = ffCellKey(r.ia);
          const label = k === "" ? blankLabel : k;
          countsIaPie[label] = (countsIaPie[label] || 0) + 1;
        }}
        let entriesIaPie = Object.keys(countsIaPie).map(function (k) {{ return [k, countsIaPie[k]]; }});
        entriesIaPie.sort(function (a, b) {{
          const sa = aoStatusSortKey(a[0], blankLabel);
          const sb = aoStatusSortKey(b[0], blankLabel);
          if (sa !== sb) return sa - sb;
          return String(a[0]).localeCompare(String(b[0]));
        }});
        entriesIaPie = entriesIaPie.map(function (p) {{
          return [iaStatusDisplayLabel(p[0], blankLabel), p[1]];
        }});
        const rowsYearPieRaw = aoRowsForYearStrip()
          .filter(function (r) {{ return rowInIaSelection(r, blankLabel); }})
          .filter(function (r) {{ return rowMatchesRatingSelection(r); }})
          .filter(function (r) {{ return rowMatchesObsTypeSelection(r, blankLabel); }});
        const rowsYearPie = sliceRowsForObsCheck(rowsYearPieRaw);
        const countsYearPie = {{}};
        for (let yi = 0; yi < rowsYearPie.length; yi++) {{
          const yr = rowsYearPie[yi];
          const yk = ffCellKey(yr.y);
          if (yk === "") continue;
          countsYearPie[yk] = (countsYearPie[yk] || 0) + 1;
        }}
        let entriesYearPie = Object.keys(countsYearPie).map(function (k) {{ return [k, countsYearPie[k]]; }});
        entriesYearPie.sort(function (a, b) {{
          return String(a[0]).localeCompare(String(b[0]), undefined, {{ numeric: true, sensitivity: "base" }});
        }});
        if (activeAuditYears.size > 0) {{
          entriesYearPie = entriesYearPie.filter(function (p) {{ return activeAuditYears.has(p[0]); }});
        }}
        const unratedLbl = ui.auditPieRatingOther || "Other";
        const rowsRatingPieRaw = fr
          .filter(function (r) {{ return rowInIaSelection(r, blankLabel); }})
          .filter(function (r) {{ return rowMatchesObsTypeSelection(r, blankLabel); }});
        const rowsRatingPie = sliceRowsForObsCheck(rowsRatingPieRaw);
        const rtCountsPie = {{}};
        (AO.rating_types || []).forEach(function (rt) {{ rtCountsPie[rt.value] = 0; }});
        let otherPie = 0;
        for (let rp = 0; rp < rowsRatingPie.length; rp++) {{
          const rv = ffCellKey(rowsRatingPie[rp].rt);
          const match = (AO.rating_types || []).find(function (x) {{ return String(x.value).toLowerCase() === rv.toLowerCase(); }});
          if (match) rtCountsPie[match.value]++;
          else otherPie++;
        }}
        let entriesRatingPie = [];
        (AO.rating_types || []).forEach(function (rt) {{
          const cnt = rtCountsPie[rt.value] || 0;
          if (cnt > 0) entriesRatingPie.push([rt.value, cnt]);
        }});
        if (otherPie > 0) entriesRatingPie.push([unratedLbl, otherPie]);
        if (activeRatingValues.size > 0) {{
          entriesRatingPie = entriesRatingPie.filter(function (p) {{
            const rt = (AO.rating_types || []).find(function (x) {{ return x.value === p[0]; }});
            if (rt) return activeRatingValues.has(String(rt.value).toLowerCase());
            if (p[0] === unratedLbl) {{
              return Array.from(activeRatingValues).some(function (k) {{
                return !(AO.rating_types || []).some(function (x) {{ return String(x.value).toLowerCase() === k; }});
              }});
            }}
            return false;
          }});
        }}
        const rowsObsPieRaw = aoSliceForObsTypes(fr, blankLabel);
        const rowsObsPie = sliceRowsForObsCheck(rowsObsPieRaw);
        const otmPie = {{}};
        for (let oi = 0; oi < rowsObsPie.length; oi++) {{
          const ok = ffCellKey(rowsObsPie[oi].ot);
          const olab = ok === "" ? blankLabel : ok;
          otmPie[olab] = (otmPie[olab] || 0) + 1;
        }}
        const pieOrder = resolveObsTypeOrder();
        let entriesObsPie = [];
        if (pieOrder.length) {{
          pieOrder.forEach(function (k) {{
            entriesObsPie.push([k, otmPie[k] || 0]);
          }});
          const seenPie = new Set(pieOrder);
          Object.keys(otmPie).sort(function (a, b) {{ return String(a).localeCompare(String(b)); }}).forEach(function (k) {{
            if (!seenPie.has(k)) entriesObsPie.push([k, otmPie[k]]);
          }});
        }} else {{
          entriesObsPie = Object.keys(otmPie).map(function (k) {{ return [k, otmPie[k]]; }});
          entriesObsPie.sort(function (a, b) {{ return String(a[0]).localeCompare(String(b[0])); }});
        }}
        if (activeObsTypeLabels.size > 0) {{
          entriesObsPie = entriesObsPie.filter(function (p) {{ return activeObsTypeLabels.has(p[0]); }});
        }}
        let metaLine = "";
        const shortlistGateOn =
          iaSelectionActive() ||
          activeRatingValues.size > 0 ||
          activeObsTypeLabels.size > 0 ||
          activeAuditYears.size > 0 ||
          shortlistToolbarSelectionActive();
        if (!fr.length) metaLine = ui.obsListEmpty || "";
        else if (!shortlistGateOn) metaLine = ui.obsNamesMetaSelect || "";
        else if (!fr2names.length) metaLine = ui.obsNoneForSelection || "";
        else metaLine = String(ui.obsNamesMetaCount || "{{n}}").replace(/\\{{n\\}}/g, String(fr2names.length));
        lastObsMetaBase = metaLine;
        lastObsChecklistN = 0;

        if (openList && openEmpty) {{
          openList.innerHTML = "";
          if (!fr.length) {{
            openEmpty.style.display = "block";
            openEmpty.textContent = ui.obsListEmpty || "";
          }} else if (!shortlistGateOn) {{
            openEmpty.style.display = "block";
            openEmpty.textContent = ui.obsSelectHint || "";
          }} else if (!fr2names.length) {{
            openEmpty.style.display = "block";
            openEmpty.textContent = ui.obsNoneForSelection || "";
          }} else {{
            openEmpty.style.display = "none";
            lastObsChecklistN = fr2names.length;
            for (let i = 0; i < fr2names.length; i++) {{
              const li = document.createElement("li");
              li.className = "audit-check-li";
              const row = fr2names[i];
              const name = row.obs == null ? "" : String(row.obs);
              const rowWrap = document.createElement("div");
              rowWrap.className = "audit-check-label";
              const labCb = document.createElement("label");
              labCb.className = "audit-obs-cb-wrap";
              const cb = document.createElement("input");
              cb.type = "checkbox";
              cb.className = "audit-obs-cb";
              cb.checked = obsCheckedIds === null || (row._idx != null && obsCheckedIds.has(row._idx));
              cb.setAttribute("aria-label", name);
              cb.addEventListener("change", function () {{
                const id = row._idx;
                if (id == null) {{
                  applyObsBarMeta();
                  return;
                }}
                if (obsCheckedIds === null) {{
                  obsCheckedIds = new Set(fr2names.map(function (x) {{ return x._idx; }}));
                }}
                if (cb.checked) obsCheckedIds.add(id);
                else obsCheckedIds.delete(id);
                if (fr2names.length === 0) {{
                  obsCheckedIds = null;
                }} else {{
                  let allOn = true;
                  for (let z = 0; z < fr2names.length; z++) {{
                    if (!obsCheckedIds.has(fr2names[z]._idx)) {{ allOn = false; break; }}
                  }}
                  if (allOn) obsCheckedIds = null;
                }}
                aoRefresh();
              }});
              labCb.appendChild(cb);
              const sp = document.createElement("button");
              sp.type = "button";
              sp.className = "audit-obs-detail-trigger";
              const spMain = document.createElement("span");
              spMain.className = "audit-obs-trigger-main";
              spMain.textContent = name;
              const spMeta = document.createElement("span");
              spMeta.className = "audit-obs-trigger-meta";
              const rtChip = document.createElement("span");
              rtChip.className = "audit-obs-meta-chip audit-obs-meta-chip--rating";
              const ratingTxt = formatObsRowRating(row);
              rtChip.textContent = (ui.obsDetailRating || "Rating") + ": " + ratingTxt;
              const rtHex = auditColorForLabel(ffCellKey(row.rt) || ratingTxt, T.h2);
              rtChip.style.background = auditMetricFillFromColor(rtHex);
              rtChip.style.borderColor = auditMetricBorderFromColor(rtHex);
              rtChip.style.color = auditMetricFgFromColor(rtHex);
              spMeta.appendChild(rtChip);
              const deptTxt = ffCellKey(row.d) || ffCellKey(row.c);
              if (deptTxt) {{
                const deptChip = document.createElement("span");
                deptChip.className = "audit-obs-meta-chip audit-obs-meta-chip--dept";
                deptChip.textContent = (ui.obsDepartmentLabel || "Department") + ": " + deptTxt;
                spMeta.appendChild(deptChip);
              }}
              if (showDetailAgingChip) {{
                const dueChip = document.createElement("span");
                dueChip.className = "audit-obs-meta-chip audit-obs-meta-chip--due";
                const dueLbl = AO.has_target_date ? (ui.obsDetailTargetDate || "Target date") : (ui.obsDetailImplDue || "Implementation due date");
                dueChip.textContent = dueLbl + ": " + implementationDueText(row);
                spMeta.appendChild(dueChip);
              }}
              sp.appendChild(spMain);
              sp.appendChild(spMeta);
              if (ui.obsDetailOpenHint) sp.title = ui.obsDetailOpenHint;
              sp.setAttribute("aria-label", ui.obsDetailOpenHint ? (ui.obsDetailOpenHint + ": " + name) : name);
              sp.addEventListener("click", function (ev) {{
                ev.preventDefault();
                ev.stopPropagation();
                openAuditObsDetail(row);
              }});
              const addNotesBtn = document.createElement("button");
              addNotesBtn.type = "button";
              addNotesBtn.className = "audit-obs-notes-add-btn";
              addNotesBtn.textContent = "+";
              addNotesBtn.setAttribute("aria-label", ui.obsNotesAddAria || "Add to notes");
              const idPick = Number(row._idx);
              if (Number.isFinite(idPick) && obsNotesPickHas(idPick)) addNotesBtn.disabled = true;
              addNotesBtn.addEventListener("click", function (ev) {{
                ev.preventDefault();
                ev.stopPropagation();
                appendObsRowToAdditionalNotes(row);
              }});
              rowWrap.appendChild(labCb);
              rowWrap.appendChild(addNotesBtn);
              rowWrap.appendChild(sp);
              li.appendChild(rowWrap);
              openList.appendChild(li);
            }}
          }}
        }}
        if (obsCheckTools) {{
          obsCheckTools.style.display = (obsNamesPanelExpanded && lastObsChecklistN > 0) ? "flex" : "none";
        }}
        try {{ updateObsNotesPickMeta(); }} catch (_oum) {{}}
        try {{ renderAdditionalNotesStack(); }} catch (_rdr) {{}}
        if ((agingCb && agingCb.checked) || (agingRevisedCb && agingRevisedCb.checked)) renderAgingMatrix(lastAgingRows);
        if (planCb && planCb.checked) renderPlanStatusTable();
        updateAuditPies(entriesIaPie, entriesYearPie, entriesRatingPie, entriesObsPie, blankLabel);
        applyObsBarMeta();
        syncBrandStripCompanies();
      }}

      buildRatingButtons();
      const auditTotalCardEl = document.getElementById("audit-total-card");
      if (auditTotalCardEl) {{
        auditTotalCardEl.addEventListener("click", function () {{
          const pair = getOpenDueIaLabelSet();
          if (!pair.length) return;
          if (openPairIaMatchesSelection()) activeIaLabels.clear();
          else {{
            activeIaLabels.clear();
            pair.forEach(function (l) {{ activeIaLabels.add(l); }});
          }}
          obsCheckedIds = null;
          aoRefresh();
        }});
        auditTotalCardEl.addEventListener("keydown", function (ev) {{
          if (ev.key === "Enter" || ev.key === " ") {{
            ev.preventDefault();
            auditTotalCardEl.click();
          }}
        }});
      }}
      // Prevent duplicated filter controls when reopening/exported HTML reruns scripts.
      if (tb) tb.innerHTML = "";
      if (brandCoHost) {{
        brandCoHost.innerHTML = "";
        brandCoHost.classList.remove("brand-company-filter-host--sc-only");
      }}
      function onAuditToolbarFilterChange(ev) {{
        const coSel = companyFilterSelectEl();
        const scSel0 = subcompanyFilterSelectEl();
        if (coSel && ev && ev.target === coSel) brandCompanyFilterReopen = false;
        activeAuditYears.clear();
        activeIaLabels.clear();
        obsCheckedIds = null;
        activeRatingValues.clear();
        activeObsTypeLabels.clear();
        aoRefresh();
        try {{
          if (typeof applyEmbeddedDeckForCompanySelection === "function") applyEmbeddedDeckForCompanySelection();
        }} catch (_edeck) {{}}
        try {{
          if (typeof rehydrateEmbeddedAltDeckIfNeeded === "function") rehydrateEmbeddedAltDeckIfNeeded();
        }} catch (_edhr) {{}}
        try {{ syncBrandLogo(); }} catch (_logoCh) {{}}
      }}
      function appendAuditDimFilterBlock(tbHost, titleText, sel, opts) {{
        opts = opts || {{}};
        const block = document.createElement("div");
        block.className = "audit-dim-filter-block";
        if (opts.plainBrandSubcompany) block.classList.add("audit-dim-filter-block--brand-sc");
        if (opts.dimKey) block.setAttribute("data-audit-dim", String(opts.dimKey));
        if (opts.hideHead) {{
          block.appendChild(sel);
          tbHost.appendChild(block);
          sel.addEventListener("change", onAuditToolbarFilterChange);
          return;
        }}
        const head = document.createElement("div");
        head.className = "audit-dim-filter-head";
        const ttl = document.createElement("span");
        ttl.className = "audit-dim-filter-title";
        ttl.textContent = titleText;
        const quick = document.createElement("div");
        quick.className = "audit-dim-filter-quick";
        const bAll = document.createElement("button");
        bAll.type = "button";
        bAll.className = "audit-dim-quick-btn";
        bAll.textContent = ui.filterDimSelectAll || "Select all";
        const bNone = document.createElement("button");
        bNone.type = "button";
        bNone.className = "audit-dim-quick-btn";
        bNone.textContent = ui.filterDimDeselectAll || "Deselect all";
        bAll.addEventListener("click", function (ev) {{
          ev.stopPropagation();
          if (!sel || !sel.options) return;
          for (let j = 0; j < sel.options.length; j++) sel.options[j].selected = true;
          sel.dispatchEvent(new Event("change", {{ bubbles: true }}));
        }});
        bNone.addEventListener("click", function (ev) {{
          ev.stopPropagation();
          if (!sel || !sel.options) return;
          for (let j = 0; j < sel.options.length; j++) sel.options[j].selected = false;
          sel.dispatchEvent(new Event("change", {{ bubbles: true }}));
        }});
        quick.appendChild(bAll);
        quick.appendChild(bNone);
        head.appendChild(ttl);
        head.appendChild(quick);
        if (opts.revealQuickOnTitleClick) {{
          quick.classList.add("audit-dim-filter-quick--collapsed");
          head.classList.add("audit-dim-filter-head--toggle-quick");
          head.setAttribute("role", "button");
          head.setAttribute("tabindex", "0");
          head.setAttribute("aria-expanded", "false");
          const syncQuickAria = function () {{
            const collapsed = quick.classList.contains("audit-dim-filter-quick--collapsed");
            head.setAttribute("aria-expanded", collapsed ? "false" : "true");
          }};
          head.addEventListener("click", function (ev) {{
            if (ev.target.closest(".audit-dim-quick-btn")) return;
            quick.classList.toggle("audit-dim-filter-quick--collapsed");
            syncQuickAria();
          }});
          head.addEventListener("keydown", function (ev) {{
            if (ev.key !== "Enter" && ev.key !== " ") return;
            ev.preventDefault();
            quick.classList.toggle("audit-dim-filter-quick--collapsed");
            syncQuickAria();
          }});
        }}
        block.appendChild(head);
        block.appendChild(sel);
        tbHost.appendChild(block);
        sel.addEventListener("change", onAuditToolbarFilterChange);
      }}
      if (companyIdx >= 0 && companyIdx !== subcompanyIdx) {{
        const cDim = dims[companyIdx];
        const companySel = document.createElement("select");
        companySel.id = brandBoxSubcompanyOnly ? "brand-filter-co" : ("ao-sel-" + companyIdx);
        companySel.multiple = true;
        companySel.setAttribute("aria-label", cDim.label || ui.companyLabel || "Company");
        const cVals = cDim.values || [];
        for (let j = 0; j < cVals.length; j++) {{
          const o = document.createElement("option");
          o.value = cVals[j];
          o.textContent = cVals[j];
          o.selected = false;
          companySel.appendChild(o);
        }}
        companySel.addEventListener("mousedown", function (ev) {{
          const t = ev.target;
          if (!t || t.tagName !== "OPTION") return;
          ev.preventDefault();
          t.selected = !t.selected;
          companySel.dispatchEvent(new Event("change", {{ bubbles: true }}));
          try {{ setTimeout(function () {{ syncBrandLogo(); }}, 0); }} catch (_logoMdCo) {{}}
        }});
        const coHost = brandBoxSubcompanyOnly ? tb : (brandCoHost || tb);
        const coReveal =
          !brandBoxSubcompanyOnly && brandCoHost ? {{ revealQuickOnTitleClick: true }} : undefined;
        appendAuditDimFilterBlock(
          coHost,
          cDim.label || ui.companyLabel || "Company",
          companySel,
          Object.assign({{ dimKey: cDim.key || "co" }}, coReveal || {{}}),
        );
      }}
      if (hasSubcompanyFilterDim && subcompanyIdx >= 0) {{
        const scDim = dims[subcompanyIdx];
        const subSel = document.createElement("select");
        subSel.id = brandBoxSubcompanyOnly ? "brand-filter-sc" : ("ao-sel-" + subcompanyIdx);
        subSel.multiple = true;
        subSel.setAttribute("aria-label", scDim.label || ui.subcompanyLabel || "Subcompany");
        const scVals = scDim.values || [];
        for (let sj = 0; sj < scVals.length; sj++) {{
          const o = document.createElement("option");
          o.value = scVals[sj];
          o.textContent = scVals[sj];
          o.selected = false;
          subSel.appendChild(o);
        }}
        subSel.addEventListener("mousedown", function (ev) {{
          const t = ev.target;
          if (!t || t.tagName !== "OPTION") return;
          ev.preventDefault();
          t.selected = !t.selected;
          subSel.dispatchEvent(new Event("change", {{ bubbles: true }}));
          try {{ setTimeout(function () {{ syncBrandLogo(); }}, 0); }} catch (_logoMd) {{}}
        }});
        appendAuditDimFilterBlock(
          brandCoHost || tb,
          scDim.label || ui.subcompanyLabel || "Subcompany",
          subSel,
          brandCoHost
            ? {{ dimKey: scDim.key || "sco", hideHead: true, plainBrandSubcompany: true }}
            : {{ dimKey: scDim.key || "sco" }},
        );
      }}
      if (brandCoHost) {{
        if (brandBoxSubcompanyOnly) brandCoHost.classList.add("brand-company-filter-host--sc-only");
        else brandCoHost.classList.remove("brand-company-filter-host--sc-only");
      }}

      dims.forEach(function (dim, i) {{
        if (dim.key === "y" || i === companyIdx || i === subcompanyIdx) return;
        const sel = document.createElement("select");
        sel.id = "ao-sel-" + i;
        sel.multiple = true;
        sel.setAttribute("aria-label", dim.label || "");
        const vals = dim.values || [];
        for (let j = 0; j < vals.length; j++) {{
          const o = document.createElement("option");
          o.value = vals[j];
          o.textContent = vals[j];
          o.selected = false;
          sel.appendChild(o);
        }}
        sel.addEventListener("mousedown", function (ev) {{
          const t = ev.target;
          if (!t || t.tagName !== "OPTION") return;
          ev.preventDefault();
          t.selected = !t.selected;
          sel.dispatchEvent(new Event("change", {{ bubbles: true }}));
        }});
        appendAuditDimFilterBlock(tb, dim.label || "", sel, {{ dimKey: dim.key || "" }});
      }});
      window.__aiExcelResetAuditChoices = function () {{
        try {{ closeAuditObsDetail(); }} catch (_e0) {{}}
        try {{ closeAgingMatrix(); }} catch (_e1) {{}}
        try {{ closePlanStatus(); }} catch (_e2) {{}}
        try {{ closeOtherReviews(); }} catch (_e3) {{}}
        resetAuditFilterSelectsToNone();
        activeAuditYears.clear();
        activeIaLabels.clear();
        activeRatingValues.clear();
        activeObsTypeLabels.clear();
        obsCheckedIds = null;
        obsNamesPanelExpanded = false;
        if (obsShowListCb) obsShowListCb.checked = false;
        try {{ syncObsNamesChecklistPanel(); }} catch (_e4) {{}}
        const saveNav = document.getElementById("save-report-html-cb");
        const saveAudit = document.getElementById("save-report-html-cb-audit");
        if (saveNav) saveNav.checked = false;
        if (saveAudit) saveAudit.checked = false;
        if (revisedDateInput && hasAgingDateSource) {{
          const now = new Date();
          revisedDateVal = formatIsoDate(new Date(now.getFullYear(), now.getMonth(), now.getDate()));
          revisedDateInput.value = revisedDateVal;
        }}
        aoRefresh();
      }};
      aoRefresh();
      setTimeout(function () {{
        hydratePersistedUserEdits();
        if (planCb && planCb.checked) renderPlanStatusTable();
      }}, 0);
    }})();

    (function applyPersistedExportReviewsFallback() {{
      function go() {{
        const el = document.getElementById("audit-dashboard-user-persist");
        if (!el || !el.textContent || !String(el.textContent).trim()) return;
        try {{
          const o = JSON.parse(el.textContent);
          if (!o || o.v !== 1 || typeof o.reviewsNote !== "string") return;
          const ta = document.getElementById("audit-reviews-textarea");
          if (!ta || String(ta.value || "").trim() !== "") return;
          ta.value = o.reviewsNote;
          try {{ localStorage.setItem("auditOtherReviewsNote", o.reviewsNote); }} catch (_lsF) {{}}
        }} catch (_e) {{}}
      }}
      go();
      setTimeout(go, 0);
    }})();

    function ffFilteredRows() {{
      if (!FF.available) return [];
      const rows = FF.rows || [];
      const fcs = FF.filter_columns || [];
      const rules = [];
      for (let i = 0; i < fcs.length; i++) {{
        const el = document.getElementById("ff-sel-" + i);
        if (!el) continue;
        const v = el.value;
        if (v === FF.all_token) continue;
        rules.push({{ key: fcs[i].key, val: v }});
      }}
      return rows.filter(function (r) {{
        for (let j = 0; j < rules.length; j++) {{
          if (ffCellKey(r[rules[j].key]) !== ffCellKey(rules[j].val)) return false;
        }}
        return true;
      }});
    }}

    function ffSortTrendLabels(keys) {{
      const mo = FF.month_order;
      if (mo && mo.length) {{
        const ord = new Map();
        mo.forEach(function (k, i) {{
          const s = String(k).trim();
          ord.set(s, i);
          ord.set(s.toLowerCase(), i);
        }});
        return keys.slice().sort(function (a, b) {{
          const sa = String(a).trim();
          const sb = String(b).trim();
          const ia = ord.has(sa) ? ord.get(sa) : (ord.has(sa.toLowerCase()) ? ord.get(sa.toLowerCase()) : 9999);
          const ib = ord.has(sb) ? ord.get(sb) : (ord.has(sb.toLowerCase()) ? ord.get(sb.toLowerCase()) : 9999);
          if (ia !== ib) return ia - ib;
          return sa.localeCompare(sb);
        }});
      }}
      return keys.slice().sort(function (a, b) {{ return String(a).localeCompare(String(b)); }});
    }}

    function ffBuildSegmentRows(subset) {{
      const seg = FF.segmentCol;
      const met = FF.metricCol;
      const sk = FF.sumKey;
      if (!seg || !met || !sk) return [];
      const map = new Map();
      for (let i = 0; i < subset.length; i++) {{
        const r = subset[i];
        const k = ffCellKey(r[seg]) || "—";
        const v = Number(r[met]);
        const add = Number.isFinite(v) ? v : 0;
        map.set(k, (map.get(k) || 0) + add);
      }}
      return Array.from(map.entries())
        .sort(function (a, b) {{ return b[1] - a[1]; }})
        .slice(0, 12)
        .map(function (pair) {{
          const o = {{ segment: pair[0] }};
          o[sk] = pair[1];
          return o;
        }});
    }}

    function ffBuildTrendRows(subset) {{
      const pc = FF.periodCol;
      const met = FF.metricCol;
      const sk = FF.sumKey;
      if (!pc || !met || !sk) return [];
      const map = new Map();
      for (let i = 0; i < subset.length; i++) {{
        const r = subset[i];
        const k = ffCellKey(r[pc]) || "—";
        const v = Number(r[met]);
        const add = Number.isFinite(v) ? v : 0;
        map.set(k, (map.get(k) || 0) + add);
      }}
      const labels = ffSortTrendLabels(Array.from(map.keys()));
      return labels.map(function (lab) {{
        const o = {{}};
        o[pc] = lab;
        o[sk] = map.get(lab);
        return o;
      }});
    }}

    function ffDrawCharts() {{
      const subset = ffFilteredRows();
      const segRows = ffBuildSegmentRows(subset);
      const trendRows = ffBuildTrendRows(subset);
      const matchEl = document.getElementById("file-filter-match");
      const loadEl = document.getElementById("file-filter-loaded");
      const ui = FF.ui || {{}};
      if (matchEl && ui.matchTpl) {{
        matchEl.textContent = ui.matchTpl
          .replace(/\\{{matched\\}}/g, String(subset.length))
          .replace(/\\{{total\\}}/g, String((FF.rows || []).length));
      }}
      if (loadEl && ui.loadedTpl) {{
        if (FF.truncated) {{
          loadEl.style.display = "block";
          loadEl.textContent = ui.loadedTpl
            .replace(/\\{{loaded\\}}/g, String((FF.rows || []).length))
            .replace(/\\{{file_total\\}}/g, String(FF.total_rows_in_file != null ? FF.total_rows_in_file : (FF.rows || []).length));
        }} else {{
          loadEl.style.display = "none";
          loadEl.textContent = "";
        }}
      }}

      if (chartSegment) {{ chartSegment.destroy(); chartSegment = null; }}
      if (chartTrend) {{ chartTrend.destroy(); chartTrend = null; }}

      const segCanvas = document.getElementById("segmentChart");
      const trCanvas = document.getElementById("trendChart");

      if (segRows.length && segCanvas) {{
        const k = Object.keys(segRows[0]).find(function (x) {{ return x !== "segment"; }}) || Object.keys(segRows[0])[1];
        chartSegment = new Chart(segCanvas, {{
          type: "bar",
          data: {{
            labels: segRows.map(function (r) {{ return r.segment; }}),
            datasets: [{{
              label: k,
              data: segRows.map(function (r) {{ return r[k]; }}),
              backgroundColor: (ctx) => {{
                const chart = ctx.chart;
                const {{ ctx: cctx, chartArea }} = chart;
                if (!chartArea) return h(T.h1, 74, 44, 0.88);
                const g = cctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top);
                g.addColorStop(0, h(T.h2, 72, 40, 0.68));
                g.addColorStop(1, h(T.h1, 76, 38, 0.92));
                return g;
              }},
              borderRadius: 8,
              borderSkipped: false
            }}]
          }},
          options: {{
            maintainAspectRatio: false,
            plugins: {{
              legend: {{ display: false }},
              tooltip: {{ callbacks: {{ label: chartTooltipBarPercentOfTotal }} }},
            }},
            scales: {{
              x: {{ grid: {{ display: false }}, ticks: {{ maxRotation: 45 }} }},
              y: {{ beginAtZero: true, grid: {{ color: "rgba(15,23,42,0.1)" }} }}
            }}
          }}
        }});
      }}

      if (trendRows.length && trCanvas) {{
        const tk = Object.keys(trendRows[0])[0];
        const vk = Object.keys(trendRows[0])[1];
        chartTrend = new Chart(trCanvas, {{
          type: "line",
          data: {{
            labels: trendRows.map(function (r) {{ return r[tk]; }}),
            datasets: [{{
              label: vk,
              data: trendRows.map(function (r) {{ return r[vk]; }}),
              borderColor: h(T.h2, 78, 48),
              backgroundColor: h(T.h2, 74, 38, 0.16),
              fill: true,
              tension: 0.35,
              pointRadius: 5,
              pointBackgroundColor: h(T.h1, 70, 48),
              pointBorderColor: "#fff",
              pointBorderWidth: 2
            }}]
          }},
          options: {{
            maintainAspectRatio: false,
            plugins: {{
              legend: {{ labels: {{ color: "#334155" }} }},
              tooltip: {{ callbacks: {{ label: chartTooltipLineSeriesPercent }} }},
            }},
            scales: {{
              x: {{ grid: {{ color: "rgba(15,23,42,0.06)" }} }},
              y: {{ grid: {{ color: "rgba(15,23,42,0.1)" }}, beginAtZero: true }}
            }}
          }}
        }});
      }}
    }}

    function initFileFilters() {{
      window.__aiExcelResetFileFilters = function () {{}};
      if (!FF.available) {{
        mountStaticSegmentTrend();
        return;
      }}
      const panel = document.getElementById("file-filter-panel");
      const toolbar = document.getElementById("file-filter-toolbar");
      const hintEl = document.getElementById("file-filter-hint");
      if (panel) panel.style.display = "block";
      if (hintEl && FF.ui && FF.ui.hint) hintEl.textContent = FF.ui.hint;
      if (!toolbar) {{
        mountStaticSegmentTrend();
        return;
      }}
      const fall = (FF.ui && FF.ui.all) ? FF.ui.all : "All";
      (FF.filter_columns || []).forEach(function (fc, idx) {{
        const wrap = document.createElement("label");
        const span = document.createElement("span");
        span.textContent = fc.label;
        const sel = document.createElement("select");
        sel.id = "ff-sel-" + idx;
        sel.setAttribute("aria-label", fc.label);
        const opts = (FF.options && FF.options[fc.key]) ? FF.options[fc.key] : [FF.all_token];
        opts.forEach(function (op) {{
          const o = document.createElement("option");
          o.value = op;
          o.textContent = (op === FF.all_token) ? fall : op;
          sel.appendChild(o);
        }});
        sel.addEventListener("change", ffDrawCharts);
        wrap.appendChild(span);
        wrap.appendChild(sel);
        toolbar.appendChild(wrap);
      }});
      window.__aiExcelResetFileFilters = function () {{
        if (!FF || !FF.available) return;
        (FF.filter_columns || []).forEach(function (_fc, idx) {{
          const el = document.getElementById("ff-sel-" + idx);
          if (el) el.value = FF.all_token;
        }});
        ffDrawCharts();
      }};
      ffDrawCharts();
    }}

    initFileFilters();

    (function initFinanceTrends() {{
      window.__aiExcelResetFinanceTrends = function () {{}};
      const ft = payload.finance_trends;
      const unEl = document.getElementById("finance-trends-unavailable");
      const bodyEl = document.getElementById("finance-trends-body");
      const hintEl = document.getElementById("ft-metric-hint");
      if (!ft || ft.available === false) {{
        if (unEl) {{
          unEl.style.display = "block";
          unEl.textContent = (ft && ft.reason) ? ft.reason : (U.ftDefaultReason || "");
        }}
        return;
      }}
      bodyEl.style.display = "block";
      hintEl.textContent = ft.hint_line || "";

      const rows = ft.detail_rows || [];
      const periodKeyMap = {{ month: "month", quarter: "quarter", year: "year" }};
      let ftPeriod = "month";
      const sel = document.getElementById("ft-category");
      (ft.categories || []).forEach(function (c) {{
        const opt = document.createElement("option");
        opt.value = c;
        opt.textContent = c === "__ALL__" ? (U.allCategories || "All categories") : c;
        sel.appendChild(opt);
      }});

      let chartLine = null;
      let chartBar = null;
      let chartStack = null;

      function sortLabels(period, labels) {{
        const u = labels.slice();
        if (period === "year") {{
          u.sort(function (a, b) {{
            return (parseFloat(a) || 0) - (parseFloat(b) || 0) || a.localeCompare(b);
          }});
          return u;
        }}
        if (period === "month") {{
          u.sort(function (a, b) {{
            if (/^\\d{{4}}-\\d{{2}}$/.test(a) && /^\\d{{4}}-\\d{{2}}$/.test(b))
              return a.localeCompare(b);
            return a.localeCompare(b);
          }});
          return u;
        }}
        u.sort(function (a, b) {{ return a.localeCompare(b); }});
        return u;
      }}

      function aggregateFiltered(catFilter) {{
        const pk = periodKeyMap[ftPeriod];
        const filtered =
          catFilter === "__ALL__"
            ? rows
            : rows.filter(function (r) {{ return r.category === catFilter; }});
        const map = new Map();
        for (let i = 0; i < filtered.length; i++) {{
          const r = filtered[i];
          const k = r[pk];
          if (!map.has(k)) map.set(k, {{ revenue: 0, expenses: 0, profit: 0 }});
          const a = map.get(k);
          a.revenue += r.revenue;
          a.expenses += r.expenses;
          a.profit += r.profit;
        }}
        const labels = sortLabels(ftPeriod, Array.from(map.keys()));
        return {{
          labels: labels,
          revenue: labels.map(function (l) {{ return map.get(l).revenue; }}),
          expenses: labels.map(function (l) {{ return map.get(l).expenses; }}),
          profit: labels.map(function (l) {{ return map.get(l).profit; }}),
        }};
      }}

      function aggregateStackRevenue() {{
        const pk = periodKeyMap[ftPeriod];
        const cats = (ft.categories || []).filter(function (c) {{ return c !== "__ALL__"; }});
        const map = new Map();
        for (let i = 0; i < rows.length; i++) {{
          const r = rows[i];
          const k = r[pk];
          if (!map.has(k)) map.set(k, {{}});
          const o = map.get(k);
          const c = r.category;
          o[c] = (o[c] || 0) + r.revenue;
        }}
        const labels = sortLabels(ftPeriod, Array.from(map.keys()));
        return {{ labels: labels, byPeriod: map, categories: cats }};
      }}

      function catHue(ci) {{
        const bases = [T.h1, T.h2, T.h3];
        const b = bases[ci % 3];
        const step = 28 * Math.floor(ci / 3);
        return (b + step) % 360;
      }}

      function drawAll() {{
        const cat = sel.value;
        const agg = aggregateFiltered(cat);
        const stk = aggregateStackRevenue();

        if (chartLine) chartLine.destroy();
        if (chartBar) chartBar.destroy();
        if (chartStack) chartStack.destroy();

        const commonOpts = {{
          maintainAspectRatio: false,
          plugins: {{
            legend: {{ labels: {{ color: "#334155" }} }},
            tooltip: {{ callbacks: {{ label: chartTooltipLineSeriesPercent }} }},
          }},
          scales: {{
            x: {{
              grid: {{ color: "rgba(15,23,42,0.06)" }},
              ticks: {{ maxRotation: 45 }},
            }},
            y: {{
              beginAtZero: true,
              grid: {{ color: "rgba(15,23,42,0.1)" }},
            }},
          }},
        }};

        chartLine = new Chart(document.getElementById("ftLineChart"), {{
          type: "line",
          data: {{
            labels: agg.labels,
            datasets: [
              {{
                label: U.revenue || "Revenue",
                data: agg.revenue,
                borderColor: h(T.h1, 76, 44),
                backgroundColor: h(T.h1, 74, 38, 0.14),
                fill: false,
                tension: 0.35,
                pointRadius: 4,
              }},
              {{
                label: U.expenses || "Expenses",
                data: agg.expenses,
                borderColor: h(T.h3, 72, 38),
                backgroundColor: h(T.h3, 70, 34, 0.14),
                fill: false,
                tension: 0.35,
                pointRadius: 4,
              }},
              {{
                label: U.profit || "Profit",
                data: agg.profit,
                borderColor: h(T.h2, 78, 46),
                backgroundColor: h(T.h2, 74, 38, 0.14),
                fill: false,
                tension: 0.35,
                pointRadius: 4,
              }},
            ],
          }},
          options: commonOpts,
        }});

        chartBar = new Chart(document.getElementById("ftBarChart"), {{
          type: "bar",
          data: {{
            labels: agg.labels,
            datasets: [
              {{
                label: U.revenue || "Revenue",
                data: agg.revenue,
                backgroundColor: h(T.h1, 74, 38, 0.82),
                borderRadius: 6,
              }},
              {{
                label: U.expenses || "Expenses",
                data: agg.expenses,
                backgroundColor: h(T.h3, 68, 34, 0.82),
                borderRadius: 6,
              }},
              {{
                label: U.profit || "Profit",
                data: agg.profit,
                backgroundColor: h(T.h2, 74, 40, 0.82),
                borderRadius: 6,
              }},
            ],
          }},
          options: {{
            maintainAspectRatio: false,
            plugins: {{
              legend: {{ labels: {{ color: "#334155" }} }},
              tooltip: {{ callbacks: {{ label: chartTooltipBarGroupPercent }} }},
            }},
            scales: {{
              x: {{ grid: {{ display: false }} }},
              y: {{
                beginAtZero: true,
                grid: {{ color: "rgba(15,23,42,0.1)" }},
              }},
            }},
          }},
        }});

        const stackDatasets = stk.categories.map(function (catName, ci) {{
          const hue = catHue(ci);
          return {{
            label: catName,
            data: stk.labels.map(function (l) {{
              const row = stk.byPeriod.get(l);
              return row && row[catName] != null ? row[catName] : 0;
            }}),
            backgroundColor: h(hue, 66, 38, 0.88),
            borderColor: h(hue, 72, 32, 0.92),
            fill: true,
            tension: 0.25,
            pointRadius: 0,
          }};
        }});

        chartStack = new Chart(document.getElementById("ftStackChart"), {{
          type: "line",
          data: {{ labels: stk.labels, datasets: stackDatasets }},
          options: {{
            maintainAspectRatio: false,
            plugins: {{
              legend: {{ labels: {{ color: "#334155" }}, position: "bottom" }},
              tooltip: {{ callbacks: {{ label: chartTooltipStackSharePercent }} }},
              title: {{
                display: true,
                text: U.stackTitle || "Revenue by category (stacked area)",
                color: "#64748b",
                font: {{ size: 13 }},
              }},
            }},
            scales: {{
              x: {{ stacked: true, grid: {{ color: "rgba(15,23,42,0.06)" }} }},
              y: {{
                stacked: true,
                beginAtZero: true,
                grid: {{ color: "rgba(15,23,42,0.1)" }},
              }},
            }},
            elements: {{ line: {{ borderWidth: 2 }}, point: {{ radius: 0 }} }},
          }},
        }});
      }}

      sel.addEventListener("change", drawAll);
      document.querySelectorAll("[data-ft-period]").forEach(function (btn) {{
        btn.addEventListener("click", function () {{
          ftPeriod = btn.getAttribute("data-ft-period");
          document.querySelectorAll("[data-ft-period]").forEach(function (b) {{
            b.classList.toggle("active", b === btn);
          }});
          drawAll();
        }});
      }});

      window.__aiExcelResetFinanceTrends = function () {{
        if (!ft || ft.available === false) return;
        if (sel && sel.options.length) sel.selectedIndex = 0;
        ftPeriod = "month";
        document.querySelectorAll("[data-ft-period]").forEach(function (b) {{
          b.classList.toggle("active", b.getAttribute("data-ft-period") === "month");
        }});
        drawAll();
      }};

      drawAll();
    }})();

    (function wireBrandLogoReset() {{
      const btn = document.getElementById("brand-logo-reset");
      if (!btn) return;
      btn.addEventListener("click", function () {{
        try {{ if (typeof window.__aiExcelResetAuditChoices === "function") window.__aiExcelResetAuditChoices(); }} catch (_ra) {{}}
        try {{ if (typeof window.__aiExcelResetFileFilters === "function") window.__aiExcelResetFileFilters(); }} catch (_rf) {{}}
        try {{ if (typeof window.__aiExcelResetFinanceTrends === "function") window.__aiExcelResetFinanceTrends(); }} catch (_rt) {{}}
      }});
      btn.addEventListener("keydown", function (ev) {{
        if (ev.key !== "Enter" && ev.key !== " ") return;
        ev.preventDefault();
        btn.click();
      }});
    }})();
  </script>
</body>
</html>
"""
    return html_out, audit_payload


def _smtp_env_pick(*keys: str) -> str:
    for k in keys:
        v = os.environ.get(k, "").strip()
        if v:
            return v
    return ""


def _smtp_config_from_env() -> dict[str, Any] | None:
    """SMTP from .env (via load_dotenv) or OS/session environment variables."""
    host = _smtp_env_pick("EXCEL_ARABIC_SMTP_HOST", "AI_EXCEL_SMTP_HOST")
    if not host:
        return None
    user = _smtp_env_pick(
        "EXCEL_ARABIC_SMTP_USER",
        "EXCEL_ARABIC_SMTP_USERNAME",
        "AI_EXCEL_SMTP_USER",
        "AI_EXCEL_SMTP_USERNAME",
    )
    password = _smtp_env_pick(
        "EXCEL_ARABIC_SMTP_PASSWORD", "AI_EXCEL_SMTP_PASSWORD"
    )
    if password:
        password = password.replace(" ", "").strip()
    from_addr = _smtp_env_pick(
        "EXCEL_ARABIC_SMTP_FROM", "AI_EXCEL_SMTP_FROM"
    ) or user
    if not from_addr:
        return None
    if not user:
        user = from_addr
    port_s = _smtp_env_pick(
        "EXCEL_ARABIC_SMTP_PORT", "AI_EXCEL_SMTP_PORT"
    ) or "587"
    try:
        port = int(port_s)
    except ValueError:
        port = 587
    tls_raw = _smtp_env_pick(
        "EXCEL_ARABIC_SMTP_USE_TLS", "AI_EXCEL_SMTP_USE_TLS"
    ).lower()
    use_tls = tls_raw not in ("0", "false", "no", "off")
    return {
        "host": host,
        "port": port,
        "use_tls": use_tls,
        "username": user,
        "password": password,
        "from": from_addr,
        "from_name": _smtp_env_pick(
            "EXCEL_ARABIC_SMTP_FROM_NAME", "AI_EXCEL_SMTP_FROM_NAME"
        ) or "ادارة المراجعة",
    }


def load_smtp_config() -> dict[str, Any] | None:
    """Load SMTP settings from project .env / environment variables only."""
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent / ".env")
    except Exception:
        pass
    return _smtp_config_from_env()


_OBS_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def _valid_obs_email(addr: str) -> bool:
    return bool(_OBS_EMAIL_RE.match(addr.strip()))


def send_audit_observation_email_smtp(
    cfg: dict[str, Any], *, to_addr: str, observation: str
) -> None:
    from accounts_app.services.email_branding import (
        format_bilingual_subject,
        send_plain_email_smtp,
    )

    observation = observation.strip()
    if not observation or len(observation) > 8000:
        raise ValueError("invalid_observation")
    to_addr = to_addr.strip()
    if not _valid_obs_email(to_addr):
        raise ValueError("invalid_recipient")

    subject = format_bilingual_subject(
        text_ar="ملاحظة تدقيق",
        text_en="Audit Observation",
    )
    body = (
        "السلام عليكم،\n\n"
        "نود إبلاغكم بخصوص الملاحظة التالية:\n"
        f"{observation}\n\n"
        "مع التحية،"
    )
    send_plain_email_smtp(cfg, to_addr=to_addr, subject=subject, plain=body)


def parse_audit_plan_pptx_bytes(
    data: bytes, *, max_bytes: int = 45 * 1024 * 1024
) -> tuple[list[dict[str, Any]], str | None]:
    """
    Extract audit-plan-like rows from a .pptx (DrawingML tables on slides).
    Returns (list of row dicts keyed by header cell text, error_code_or_none).
    """
    import xml.etree.ElementTree as ET

    if len(data) > max_bytes:
        return [], "too_large"

    NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"

    def cell_txt(tc: ET.Element) -> str:
        bits: list[str] = []
        for t in tc.iter(f"{{{NS_A}}}t"):
            bits.append(t.text or "")
        s = "".join(bits)
        return " ".join(s.replace("\u00a0", " ").split())

    def tbl_to_rows(tbl: ET.Element) -> list[list[str]]:
        out: list[list[str]] = []
        for tr in tbl.findall(f"{{{NS_A}}}tr"):
            row: list[str] = []
            for tc in tr.findall(f"{{{NS_A}}}tc"):
                row.append(cell_txt(tc))
            out.append(row)
        return out

    def norm_cell(x: object) -> str:
        s = str(x or "").strip().lower().replace("%", " ").replace("_", " ").replace("-", " ")
        return re.sub(r"\s+", " ", s).strip()

    def score_matrix(m: list[list[str]]) -> int:
        if not m or not m[0] or len(m[0]) < 4:
            return -1
        score = len(m) * 10 + len(m[0])
        joined = " ".join(norm_cell(h) for h in m[0])
        if re.search(r"project|auditable|planning|field|reporting|resource|status", joined, re.I):
            score += 200
        return score

    def slide_key(name: str) -> int:
        mm = re.search(r"(\d+)", name)
        return int(mm.group(1)) if mm else 0

    try:
        with zipfile.ZipFile(BytesIO(data), "r") as zf:
            slides = sorted(
                [n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n, re.I)],
                key=slide_key,
            )
            mats: list[list[list[str]]] = []
            for sn in slides:
                try:
                    root = ET.fromstring(zf.read(sn))
                except ET.ParseError:
                    continue
                for tbl in root.findall(f".//{{{NS_A}}}tbl"):
                    mat = tbl_to_rows(tbl)
                    if mat:
                        mats.append(mat)
    except zipfile.BadZipFile:
        return [], "bad_zip"
    except Exception as exc:
        return [], str(exc)[:240]

    if not mats:
        return [], "no_table"

    best: list[list[str]] | None = None
    best_score = -1
    for m in mats:
        s = score_matrix(m)
        if s > best_score:
            best_score = s
            best = m
    if best is None:
        return [], "no_table"
    if best_score < 0:
        best = max(mats, key=lambda m: len(m) * len(m[0]) if m and m[0] else 0)

    hdr_i = 0
    for i in range(min(3, len(best))):
        joined = " ".join(norm_cell(x) for x in best[i])
        if re.search(r"project|auditable|planning|field|reporting|resource|status", joined, re.I):
            hdr_i = i
            break

    hdr = best[hdr_i]
    rows_out: list[dict[str, Any]] = []
    for vals in best[hdr_i + 1 :]:
        rec: dict[str, Any] = {}
        for j, h in enumerate(hdr):
            rec[str(h)] = vals[j] if j < len(vals) else ""
        rows_out.append(rec)
    return rows_out, None


if __name__ == "__main__":
    import subprocess

    print("Use Django: python manage.py runserver 127.0.0.1:8000")
    env = os.environ.copy()
    env.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    subprocess.run(
        [sys.executable, "manage.py", "runserver", "127.0.0.1:8000"],
        check=False,
        env=env,
    )
