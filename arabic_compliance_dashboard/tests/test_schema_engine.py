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


def test_validate_schema_without_risk_columns():
    df = _sample_df().drop(columns=["تصنيف المخاطر الكامنة", "تصنيف المخاطر المتبقية"])
    resolved = validate_schema(df, locale="ar")
    assert "inherent" not in resolved
    assert "residual" not in resolved
    assert "status" in resolved


def test_normalize_and_rows():
    df = normalize_dataframe(_sample_df())
    assert "اسم النظام" in df.columns
    assert "النص النظامي" in df.columns
    assert "السنة" in df.columns
    rows = rows_from_dataframe(df)
    assert len(rows) == 1
    assert rows[0]["النص النظامي"] == "نص نظامي تجريبي"


def test_year_inferred_from_target_date_when_year_column_missing():
    df = pd.DataFrame(
        [
            {
                "الحالة": "مفتوح",
                "الإدارة المسؤولة": "إدارة IT",
                "المشرع": "وزارة التجارة",
                "اسم النظام": "نظام",
                "الهيئة التابعة": "0",
                "اللائحة": "لائحة",
                "النص النظامي": "نص",
                "حالة الالتزام": "غيرملتزم",
                "فئة الضوابط الرقابية": "سياسات",
                "تاريخ التصحيح المستهدف": "2026-03-15",
            },
            {
                "الحالة": "مفتوح",
                "الإدارة المسؤولة": "إدارة IT",
                "المشرع": "وزارة التجارة",
                "اسم النظام": "نظام",
                "الهيئة التابعة": "0",
                "اللائحة": "لائحة",
                "النص النظامي": "نص 2",
                "حالة الالتزام": "غيرملتزم",
                "فئة الضوابط الرقابية": "سياسات",
                "تاريخ التصحيح المستهدف": "",
            },
        ]
    )
    rows = rows_from_dataframe(df)
    assert rows[0]["السنة"] == "2026"
    assert rows[1]["السنة"] == "(blank)"


def test_year_keeps_explicit_excel_value():
    rows = rows_from_dataframe(normalize_dataframe(_sample_df()))
    assert rows[0]["السنة"] == "2026"


def test_build_summary_filter():
    from arabic_compliance_dashboard.engine import PARAM_TO_COL

    df = normalize_dataframe(_sample_df())
    rows = rows_from_dataframe(df)
    selected = {col: [] for col in PARAM_TO_COL.values()}
    summary = build_summary(rows, selected)
    assert summary["total"] == 1
    assert "الحالة" in summary["groups"]


def test_compute_aging_open_status():
    from arabic_compliance_dashboard.engine import (
        COL_RESIDUAL,
        COL_STATUS,
        COL_TARGET,
        PARAM_TO_COL,
    )

    df = normalize_dataframe(_sample_df())
    rows = rows_from_dataframe(df)
    selected = {col: [] for col in PARAM_TO_COL.values()}
    out = compute_aging(rows, selected, "2026-06-01", "target")
    assert "error" not in out
    not_due = next(r for r in out["time_rows"] if r["id"] == "not_due")
    assert not_due["total"] == 1
    assert out["grand_total"] == 1


def test_compute_aging_past_status_buckets():
    from arabic_compliance_dashboard.engine import (
        COL_RESIDUAL,
        COL_STATUS,
        COL_TARGET,
        PARAM_TO_COL,
    )

    rows = [
        {
            COL_STATUS: "مفتوح ( تجاوز تاريخ التصحيح)",
            COL_RESIDUAL: "متوسط",
            COL_TARGET: "2026-01-01",
        }
    ]
    selected = {col: [] for col in PARAM_TO_COL.values()}
    out = compute_aging(rows, selected, "2026-06-01", "target")
    lt_6m = next(r for r in out["time_rows"] if r["id"] == "lt_6m")
    assert lt_6m["cells"]["medium"] == 1
    assert out["grand_total"] == 1


def test_compute_aging_modified_date_source():
    from arabic_compliance_dashboard.engine import (
        COL_MODIFIED,
        COL_RESIDUAL,
        COL_STATUS,
        PARAM_TO_COL,
    )

    rows = [
        {
            COL_STATUS: "مفتوح ( تجاوز تاريخ التصحيح)",
            COL_RESIDUAL: "مرتفع",
            COL_MODIFIED: "2024-01-01",
        }
    ]
    selected = {col: [] for col in PARAM_TO_COL.values()}
    out = compute_aging(rows, selected, "2026-06-01", "modified")
    ge_1y = next(r for r in out["time_rows"] if r["id"] == "ge_1y")
    assert ge_1y["cells"]["high"] == 1


def test_compute_aging_uses_inherent_risk_when_residual_missing():
    from arabic_compliance_dashboard.engine import (
        COL_INHERENT,
        COL_STATUS,
        COL_TARGET,
        PARAM_TO_COL,
    )

    rows = [
        {
            COL_STATUS: "مفتوح ( ضمن تاريخ التصحيح)",
            COL_INHERENT: "عالي",
            COL_TARGET: "2026-12-01",
        }
    ]
    selected = {col: [] for col in PARAM_TO_COL.values()}
    out = compute_aging(rows, selected, "2026-06-01", "target")
    not_due = next(r for r in out["time_rows"] if r["id"] == "not_due")
    assert not_due["cells"]["high"] == 1


def test_resolve_columns_accepts_mosot_al_khatr_aliases():
    df = _sample_df().rename(
        columns={
            "تصنيف المخاطر الكامنة": "مستوى المخاطر الكامنة",
            "تصنيف المخاطر المتبقية": "مستوى المخاطر المتبقية",
        }
    )
    resolved = resolve_columns(df)
    assert resolved["inherent"] == "مستوى المخاطر الكامنة"
    assert resolved["residual"] == "مستوى المخاطر المتبقية"
