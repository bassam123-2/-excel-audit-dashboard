#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd


def _norm_col(name: Any) -> str:
    return str(name).strip().lower().replace("_", " ")


def _pick_col(columns: list[str], keywords: tuple[str, ...]) -> str | None:
    for c in columns:
        n = _norm_col(c)
        if any(k in n for k in keywords):
            return c
    return None


def _risk_label(value: Any) -> str:
    s = str(value).strip().lower()
    if not s or s == "nan":
        return "medium"
    if "مرتفع جدا" in s or "very high" in s or "critical" in s:
        return "very_high"
    if "مرتفع" in s or "high" in s:
        return "high"
    if "متوسط" in s or "medium" in s or "moderate" in s:
        return "medium"
    if "منخفض" in s or "low" in s:
        return "low"
    return "medium"


def _risk_score_from_label(label: str) -> int:
    if label == "very_high":
        return 14
    if label == "high":
        return 10
    if label == "medium":
        return 6
    return 2


def _summarize(df: pd.DataFrame, col: str, risk_col: str) -> list[dict[str, Any]]:
    if not col:
        return []
    work = df[[col, risk_col]].copy()
    work = work[work[col].notna()]
    if work.empty:
        return []
    work["risk_label"] = work[risk_col].map(_risk_label)
    out = []
    for name, g in work.groupby(col, dropna=True):
        vhi = int((g["risk_label"] == "very_high").sum())
        hi = int((g["risk_label"] == "high").sum())
        mid = int((g["risk_label"] == "medium").sum())
        low = int((g["risk_label"] == "low").sum())
        total = int(len(g))
        avg = round(
            (
                vhi * _risk_score_from_label("very_high")
                + hi * _risk_score_from_label("high")
                + mid * _risk_score_from_label("medium")
                + low * _risk_score_from_label("low")
            )
            / max(total, 1),
            1,
        )
        out.append(
            {
                "name": str(name),
                "total": total,
                "cnt": total,
                "avg": avg,
                "hi": vhi,
                "h": hi,
                "m": mid,
                "l": low,
            }
        )
    out.sort(key=lambda x: (x["avg"], x["total"]), reverse=True)
    return out


def _build_lookup(
    df: pd.DataFrame,
    key_col: str,
    issuer_col: str | None,
    system_col: str | None,
    haia_col: str | None,
    laiha_col: str | None,
    dept_col: str | None,
) -> dict[str, dict[str, int]]:
    if not key_col:
        return {}
    out: dict[str, dict[str, int]] = {}
    for key_val, g in df[df[key_col].notna()].groupby(key_col):
        out[str(key_val)] = {
            "t": int(len(g)),
            "i": int(g[issuer_col].nunique(dropna=True)) if issuer_col else 0,
            "s": int(g[system_col].nunique(dropna=True)) if system_col else 0,
            "h": int(g[haia_col].nunique(dropna=True)) if haia_col else 0,
            "l": int(g[laiha_col].nunique(dropna=True)) if laiha_col else 0,
            "d": int(g[dept_col].nunique(dropna=True)) if dept_col else 0,
        }
    return out


def _replace_var_block(html: str, var_name: str, value_obj: Any) -> str:
    js = json.dumps(value_obj, ensure_ascii=False)
    pattern = rf"var\s+{re.escape(var_name)}\s*=\s*.*?;"
    return re.sub(pattern, f"var {var_name}={js};", html, flags=re.S)


def _replace_element_text(html: str, element_id: str, value: Any) -> str:
    pattern = rf'(<[^>]*id="{re.escape(element_id)}"[^>]*>)(.*?)(</[^>]+>)'
    return re.sub(pattern, rf"\g<1>{value}\g<3>", html, flags=re.S)


def render_from_reference(
    df: pd.DataFrame,
    reference_html_path: str,
) -> str:
    with open(reference_html_path, "r", encoding="utf-8") as f:
        html = f.read()

    cols = [str(c) for c in df.columns]
    issuer_col = _pick_col(cols, ("issuer", "المشرع", "جهة"))
    system_col = _pick_col(cols, ("system", "النظام"))
    haia_col = _pick_col(cols, ("authority", "agency", "الهيئة"))
    laiha_col = _pick_col(cols, ("regulation", "bylaw", "اللائحة"))
    dept_col = _pick_col(cols, ("department", "owner", "responsible", "الإدارة"))
    risk_col = _pick_col(cols, ("risk", "تصنيف الخطر", "مستوى المخاطر"))
    if not risk_col:
        risk_col = cols[0]

    da = _summarize(df, dept_col, risk_col) if dept_col else []
    sys = _summarize(df, system_col, risk_col) if system_col else []
    laiha = _summarize(df, laiha_col, risk_col) if laiha_col else []
    haia = _summarize(df, haia_col, risk_col) if haia_col else []
    iss = _summarize(df, issuer_col, risk_col) if issuer_col else []

    # Keep same panel density as reference.
    sys = sys[:12]
    laiha = laiha[:15]

    full_counts = {
        "issuer": int(df[issuer_col].nunique(dropna=True)) if issuer_col else 0,
        "system": int(df[system_col].nunique(dropna=True)) if system_col else 0,
        "haia": int(df[haia_col].nunique(dropna=True)) if haia_col else 0,
        "laiha": int(df[laiha_col].nunique(dropna=True)) if laiha_col else 0,
        "dept": int(df[dept_col].nunique(dropna=True)) if dept_col else 0,
        "texts": int(len(df)),
    }

    lookup = {
        "dept": _build_lookup(df, dept_col, issuer_col, system_col, haia_col, laiha_col, dept_col)
        if dept_col
        else {},
        "systems": _build_lookup(
            df, system_col, issuer_col, system_col, haia_col, laiha_col, dept_col
        )
        if system_col
        else {},
        "laiha": _build_lookup(df, laiha_col, issuer_col, system_col, haia_col, laiha_col, dept_col)
        if laiha_col
        else {},
        "haia": _build_lookup(df, haia_col, issuer_col, system_col, haia_col, laiha_col, dept_col)
        if haia_col
        else {},
        "issuer": _build_lookup(
            df, issuer_col, issuer_col, system_col, haia_col, laiha_col, dept_col
        )
        if issuer_col
        else {},
    }

    # Plans from dept summary
    plan3y = []
    plan2026 = []
    for r in da[:14]:
        level = "مرتفع" if r["avg"] > 8 else "متوسط" if r["avg"] > 4 else "منخفض"
        plan3y.append(
            {
                "name": r["name"],
                "count": r["total"],
                "score": r["avg"],
                "level": level,
                "y26": level if r["avg"] > 8 else "",
                "y27": level,
                "y28": level if r["avg"] > 6 else "",
            }
        )
        plan2026.append(
            {
                "name": r["name"],
                "count": r["total"],
                "score": r["avg"],
                "level": level,
                "q2": level if r["avg"] > 9 else "",
                "q3": level if 6 < r["avg"] <= 9 else "",
                "q4": level if r["avg"] <= 6 else "",
            }
        )

    total = max(len(df), 1)
    vhi = int(sum(x["hi"] for x in da)) if da else 0
    hi = int(sum(x["h"] for x in da)) if da else 0
    mid = int(sum(x["m"] for x in da)) if da else 0
    low = int(sum(x["l"] for x in da)) if da else 0

    html = _replace_var_block(html, "DA", da)
    html = _replace_var_block(html, "SYS", sys)
    html = _replace_var_block(html, "LAIHA", laiha)
    html = _replace_var_block(html, "HAIA", haia)
    html = _replace_var_block(html, "ISS", iss)
    html = _replace_var_block(html, "FULL_COUNTS", full_counts)
    html = _replace_var_block(html, "LOOKUP", lookup)
    html = _replace_var_block(html, "PLAN3Y", plan3y)
    html = _replace_var_block(html, "PLAN2026", plan2026)

    # Initial visible counters
    html = _replace_element_text(html, "sb-issuer", full_counts["issuer"])
    html = _replace_element_text(html, "sb-system", full_counts["system"])
    html = _replace_element_text(html, "sb-haia", full_counts["haia"])
    html = _replace_element_text(html, "sb-laiha", full_counts["laiha"])
    html = _replace_element_text(html, "sb-dept", full_counts["dept"])
    html = _replace_element_text(html, "sb-texts", full_counts["texts"])

    html = _replace_element_text(html, "kpi-total", total)
    html = _replace_element_text(html, "kpi-total-note", f"{total} نص نظامي")
    html = _replace_element_text(html, "kpi-vhi", vhi)
    html = _replace_element_text(html, "kpi-vhi-pct", f"{round(vhi / total * 100, 1)}%")
    html = _replace_element_text(html, "kpi-hi", hi)
    html = _replace_element_text(html, "kpi-hi-pct", f"{round(hi / total * 100, 1)}%")
    html = _replace_element_text(html, "kpi-mid", mid)
    html = _replace_element_text(html, "kpi-mid-pct", f"{round(mid / total * 100, 1)}%")
    html = _replace_element_text(html, "kpi-lo", low)
    html = _replace_element_text(html, "kpi-lo-pct", f"{round(low / total * 100, 1)}%")

    return html
