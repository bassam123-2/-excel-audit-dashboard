"""Tests for Arabic compliance dashboard schema and engine."""
from __future__ import annotations

import pandas as pd
import pytest

from arabic_compliance_dashboard.engine import build_summary, compute_aging
from arabic_compliance_dashboard.schema import (
    normalize_dataframe,
    resolve_columns,
    rows_from_dataframe,
    validate_schema,
)


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "تصنيف المخاطر الكامنة": "مرتفع",
                "تصنيف المخاطر المتبقية": "متوسط",
                "الحالة": "مفتوح ( ضمن تاريخ التصحيح)",
                "الإدارة المسؤولة": "إدارة IT",
                "المشرع": "وزارة التجارة",
                "النظام": "نظام تجاري",
                "الهيئة التابعة": "0",
                "اللائحة": "لائحة",
                "النص بالكامل": "نص نظامي تجريبي",
                "حالة الالتزام": "ملتزم جزئي",
                "فئة الضوابط الرقابية": "سياسات",
                "السنوات": "2026",
                "تاريخ التصحيح المستهدف": "2026-01-01",
            }
        ]
    )


def test_resolve_columns_aliases():
    df = _sample_df()
    resolved = resolve_columns(df)
    assert "system_name" in resolved
    assert "legal_text" in resolved
    assert "year" in resolved


def test_validate_schema_missing_column():
    df = _sample_df().drop(columns=["الحالة"])
    with pytest.raises(ValueError, match="الحالة|Missing"):
        validate_schema(df, locale="ar")


def test_normalize_and_rows():
    df = normalize_dataframe(_sample_df())
    assert "اسم النظام" in df.columns
    assert "النص النظامي" in df.columns
    assert "السنة" in df.columns
    rows = rows_from_dataframe(df)
    assert len(rows) == 1
    assert rows[0]["النص النظامي"] == "نص نظامي تجريبي"


def test_build_summary_filter():
    from arabic_compliance_dashboard.engine import PARAM_TO_COL

    df = normalize_dataframe(_sample_df())
    rows = rows_from_dataframe(df)
    selected = {col: [] for col in PARAM_TO_COL.values()}
    summary = build_summary(rows, selected)
    assert summary["total"] == 1
    assert "الحالة" in summary["groups"]


def test_compute_aging_open_status():
    from arabic_compliance_dashboard.engine import PARAM_TO_COL

    df = normalize_dataframe(_sample_df())
    rows = rows_from_dataframe(df)
    selected = {col: [] for col in PARAM_TO_COL.values()}
    out = compute_aging(rows, selected, "2026-06-01", "target")
    assert "error" not in out
    assert out["grand_total"] >= 0
