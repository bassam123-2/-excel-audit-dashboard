"""Arabic compliance dashboard — Excel column schema and validation."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any

import pandas as pd

from audit_app.dashboard_template_codes import TEMPLATE_CODE_CD

TEMPLATE_CODE = TEMPLATE_CODE_CD
BLANK = "(blank)"

# Logical key -> canonical Arabic column name + accepted header aliases
REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "status": ("الحالة",),
    "department": ("الإدارة المسؤولة",),
    "legislator": ("المشرع",),
    "system_name": ("اسم النظام", "النظام"),
    "authority": ("الهيئة التابعة",),
    "regulation": ("اللائحة",),
    "legal_text": ("النص النظامي", "النص بالكامل"),
    "compliance_status": ("حالة الالتزام",),
    "control_category": ("فئة الضوابط الرقابية",),
}

OPTIONAL_COLUMNS: dict[str, tuple[str, ...]] = {
    "inherent": ("تصنيف المخاطر الكامنة", "مستوى المخاطر الكامنة"),
    "residual": ("تصنيف المخاطر المتبقية", "مستوى المخاطر المتبقية"),
    "year": ("السنوات", "السنة"),
    "target_date": ("تاريخ التصحيح المستهدف",),
    "modified_date": ("تاريخ التصحيح المعدل",),
    "holding_company": ("الشركة القابضة",),
    "subsidiary_company": ("الشركة التابعة",),
    "task_owner": ("مالك المهمة / مالك الإجراء",),
    "responsible_person": ("الشخص المسؤول",),
    "corrective_plan": ("الخطة التصحيحية",),
    "mgmt_notes": ("ملاحظات الإدارة",),
    "compliance_notes": ("ملاحظات الإلتزام", "ملاحظات الالتزام"),
    "email": ("email", "البريد الإلكتروني"),
}

# Canonical names used in dashboard rows (after normalization)
CANONICAL_NAMES: dict[str, str] = {
    "inherent": "تصنيف المخاطر الكامنة",
    "residual": "تصنيف المخاطر المتبقية",
    "status": "الحالة",
    "department": "الإدارة المسؤولة",
    "legislator": "المشرع",
    "system_name": "اسم النظام",
    "authority": "الهيئة التابعة",
    "regulation": "اللائحة",
    "legal_text": "النص النظامي",
    "compliance_status": "حالة الالتزام",
    "control_category": "فئة الضوابط الرقابية",
    "year": "السنة",
    "target_date": "تاريخ التصحيح المستهدف",
    "modified_date": "تاريخ التصحيح المعدل",
    "holding_company": "الشركة القابضة",
    "subsidiary_company": "الشركة التابعة",
    "task_owner": "مالك المهمة / مالك الإجراء",
    "responsible_person": "الشخص المسؤول",
    "corrective_plan": "الخطة التصحيحية",
    "mgmt_notes": "ملاحظات الإدارة",
    "compliance_notes": "ملاحظات الإلتزام",
    "email": "email",
}

EXCEL_EXTENSIONS = {".xlsx", ".xls", ".xlsm"}


def _norm_header(value: Any) -> str:
    s = unicodedata.normalize("NFKC", str(value or "").strip())
    return " ".join(s.split()).casefold()


def _build_header_map(columns: list[Any]) -> dict[str, str]:
    """Map normalized header -> original column name."""
    out: dict[str, str] = {}
    for col in columns:
        key = _norm_header(col)
        if key and key not in out:
            out[key] = str(col)
    return out


def resolve_columns(df: pd.DataFrame) -> dict[str, str]:
    """Resolve logical keys to actual DataFrame column names."""
    header_map = _build_header_map(list(df.columns))
    resolved: dict[str, str] = {}
    for logical, aliases in {**REQUIRED_COLUMNS, **OPTIONAL_COLUMNS}.items():
        for alias in aliases:
            key = _norm_header(alias)
            if key in header_map:
                resolved[logical] = header_map[key]
                break
    modified_prefix = _norm_header("تاريخ التصحيح المعدل")
    if "modified_date" not in resolved:
        for key, actual in header_map.items():
            if key.startswith(modified_prefix):
                resolved["modified_date"] = actual
                break
    return resolved


def year_from_date_cell(value: Any) -> str:
    """Extract calendar year from a date cell; return BLANK when missing or unparseable."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return BLANK
    s = str(value).strip()
    if not s or s == BLANK:
        return BLANK
    try:
        if "T" in s:
            return str(datetime.fromisoformat(s.replace("Z", "")).year)
        if re.fullmatch(r"-?\d+(?:\.\d+)?", s):
            fv = float(s)
            if fv >= 1e12:
                return str(datetime.utcfromtimestamp(fv / 1000.0).year)
            if 1e9 <= fv < 1e12:
                return str(datetime.utcfromtimestamp(fv).year)
        return str(datetime.strptime(s[:10], "%Y-%m-%d").year)
    except ValueError:
        return BLANK


def enrich_row_year(row: dict[str, str]) -> dict[str, str]:
    """Fill السنة from تاريخ التصحيح المستهدف when year is absent or blank."""
    year_col = CANONICAL_NAMES["year"]
    target_col = CANONICAL_NAMES["target_date"]
    existing = row.get(year_col, BLANK)
    if existing and existing != BLANK:
        return row
    row[year_col] = year_from_date_cell(row.get(target_col))
    return row


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rename columns to canonical Arabic names and drop duplicate alias columns.
    Returns a new DataFrame.
    """
    colmap = resolve_columns(df)
    rename: dict[str, str] = {}
    for logical, src_col in colmap.items():
        canonical = CANONICAL_NAMES.get(logical)
        if canonical and src_col in df.columns:
            rename[src_col] = canonical
    out = df.rename(columns=rename)
    # Keep only canonical + any unmapped columns that aren't duplicates
    keep = list(dict.fromkeys(rename.values()))
    extra = [c for c in out.columns if c not in keep and c not in rename]
    return out[[c for c in keep if c in out.columns] + extra]


def _err(locale: str, ar: str, en: str) -> str:
    return ar if locale == "ar" else en


def validate_schema(df: pd.DataFrame, locale: str = "ar") -> dict[str, str]:
    """
    Validate required columns exist and at least one data row remains.
    Returns resolved logical->column map.
    Raises ValueError with user-facing message on failure.
    """
    if df is None or df.empty:
        raise ValueError(
            _err(locale, "الملف فارغ أو لا يحتوي على بيانات.", "File is empty or has no data.")
        )

    resolved = resolve_columns(df)
    missing = []
    for logical, aliases in REQUIRED_COLUMNS.items():
        if logical not in resolved:
            missing.append(aliases[0])

    if missing:
        joined = "، ".join(missing)
        raise ValueError(
            _err(
                locale,
                f"أعمدة إلزامية ناقصة: {joined}",
                f"Missing required columns: {', '.join(missing)}",
            )
        )

    # At least one non-empty row after dropping all-null rows
    data = df.dropna(how="all")
    if data.empty:
        raise ValueError(
            _err(
                locale,
                "لا توجد صفوف بيانات في الملف.",
                "No data rows found in the file.",
            )
        )

    return resolved


def rows_from_dataframe(df: pd.DataFrame) -> list[dict[str, str]]:
    """Convert normalized DataFrame to list of row dicts with BLANK for empty cells."""
    normalized = normalize_dataframe(df)
    rows: list[dict[str, str]] = []
    for _, series in normalized.iterrows():
        row: dict[str, str] = {}
        for col in normalized.columns:
            val = series[col]
            if pd.isna(val) or str(val).strip() == "":
                row[str(col)] = BLANK
            else:
                row[str(col)] = str(val).strip()
        enrich_row_year(row)
        rows.append(row)
    return rows
