"""Shared Excel/CSV loading for the dashboard tools.

See docs/FOLDER_MAP.md and docs/ARCHITECTURE.md."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

import pandas as pd

ATTR_READ_NOTES = "dashboard_read_notes"


def _excel_sheet(sheet_name: str | int | None) -> str | int:
    """pandas treats sheet_name=None as 'all sheets' (returns dict). We use the first sheet."""
    return 0 if sheet_name is None else sheet_name


def _unique_names(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for raw in names:
        base = (raw or "").strip() or "Column"
        n = seen.get(base, 0) + 1
        seen[base] = n
        out.append(base if n == 1 else f"{base}_{n}")
    return out


def _is_unnamed_col(name: object) -> bool:
    s = str(name).strip()
    if not s or s.lower() == "nan":
        return True
    return bool(re.match(r"^Unnamed:\s*\d+\s*$", s, re.I))


def _sanitize_columns_inplace(df: pd.DataFrame, notes: list[str]) -> None:
    """Replace pandas 'Unnamed: k' with Col_1, Col_2, … (1-based)."""
    cols = list(df.columns)
    if not any(_is_unnamed_col(c) for c in cols):
        return
    new_names: list[str] = []
    unnamed_count = 0
    for i, c in enumerate(cols):
        if _is_unnamed_col(c):
            unnamed_count += 1
            new_names.append(f"Col_{i + 1}")
        else:
            new_names.append(str(c).strip())
    df.columns = _unique_names(new_names)
    notes.append("read_unnamed_renamed")


def _score_header_row(row: pd.Series) -> float:
    """Prefer rows that look like titles (mostly text, not pure numbers)."""
    vals = [row.iloc[j] for j in range(len(row)) if pd.notna(row.iloc[j])]
    if len(vals) < 2:
        return -1000.0
    str_n = 0
    num_n = 0
    for v in vals:
        if isinstance(v, str) and str(v).strip():
            str_n += 1
            continue
        if pd.api.types.is_number(v) and not isinstance(v, bool):
            num_n += 1
            continue
        try:
            float(str(v).replace(",", "").strip())
            num_n += 1
        except (TypeError, ValueError):
            str_n += 1
    return float(str_n) - 0.55 * float(num_n)


def _read_excel_guess_header(path: str, sheet: str | int) -> pd.DataFrame:
    """When row 0 is mostly empty/merged, find a better header row (first ~15 rows)."""
    raw = pd.read_excel(
        path,
        sheet_name=sheet,
        dtype=object,
        header=None,
        nrows=80,
    )
    if raw.shape[0] < 2:
        return pd.read_excel(path, sheet_name=sheet, dtype=object, header=0)

    best_i = 0
    best_sc = _score_header_row(raw.iloc[0])
    search_n = min(15, len(raw))
    for i in range(1, search_n):
        sc = _score_header_row(raw.iloc[i])
        if sc > best_sc:
            best_sc = sc
            best_i = i

    # Row 0 wins unless a lower row is clearly better (more "header-like").
    if best_i == 0 or best_sc < 1.0:
        return pd.read_excel(path, sheet_name=sheet, dtype=object, header=0)

    df = pd.read_excel(path, sheet_name=sheet, dtype=object, header=best_i)
    if not hasattr(df, "attrs") or df.attrs is None:
        df.attrs = {}
    notes_holder = df.attrs.get(ATTR_READ_NOTES, [])
    notes_list = list(notes_holder) if isinstance(notes_holder, list) else []
    notes_list.append(f"read_header_row:{best_i + 1}")
    df.attrs[ATTR_READ_NOTES] = notes_list
    return df


def _openai_suggest_labels(
    df: pd.DataFrame,
    *,
    locale: str,
) -> dict[str, str] | None:
    """Optional: use OpenAI to suggest short column titles for Col_* / generic names."""
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        return None
    targets = [str(c) for c in df.columns if re.match(r"^Col_\d+$", str(c))]
    if len(targets) < 1:
        return None

    samples: dict[str, list[str]] = {}
    for c in targets:
        ser = df[c].dropna().head(8)
        samples[c] = [str(x)[:120] for x in ser.tolist()]

    lang = "Arabic" if locale.startswith("ar") else "English"
    payload = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": [
            {
                "role": "system",
                "content": (
                    "You label spreadsheet columns for a finance dashboard. "
                    f"Reply with a single JSON object mapping each input key to a short "
                    f"column title (max 40 chars) in {lang}. Use professional tone. "
                    "If values look like company names, amounts, or dates, reflect that. "
                    "No markdown, only JSON."
                ),
            },
            {"role": "user", "content": json.dumps(samples, ensure_ascii=False)},
        ],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        text = data["choices"][0]["message"]["content"].strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        mapping = json.loads(text)
        if not isinstance(mapping, dict):
            return None
        out: dict[str, str] = {}
        for k, v in mapping.items():
            if k in targets and isinstance(v, str) and v.strip():
                out[k] = v.strip()[:80]
        return out or None
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, IndexError, TypeError):
        return None


def _maybe_ai_rename_columns(df: pd.DataFrame, notes: list[str], locale: str) -> pd.DataFrame:
    mapping = _openai_suggest_labels(df, locale=normalize_locale_for_file(locale))
    if not mapping:
        return df
    df = df.rename(columns=mapping)
    df.columns = _unique_names([str(c) for c in df.columns])
    notes.append("read_ai_labels")
    return df


def normalize_locale_for_file(locale: str | None) -> str:
    if not locale:
        return "en"
    loc = str(locale).strip().lower()
    return "ar" if loc.startswith("ar") else "en"


def read_input_file(
    path: str,
    sheet_name: str | None = None,
    *,
    locale: str | None = None,
) -> pd.DataFrame:
    """
    Load Excel/CSV. Excel: guess header row when row 0 yields many Unnamed columns.
    Sets df.attrs['dashboard_read_notes'] with codes for the report (translated later).
    If OPENAI_API_KEY is set, may rename Col_* columns using a short API call.
    """
    ext = os.path.splitext(path)[1].lower()
    notes: list[str] = []
    loc = normalize_locale_for_file(locale)

    if ext in {".xlsx", ".xlsm", ".xls"}:
        sheet = _excel_sheet(sheet_name)
        probe = pd.read_excel(path, sheet_name=sheet, dtype=object, header=0, nrows=5)
        if isinstance(probe, dict):
            raise ValueError("Expected one worksheet; pass a sheet name or index.")
        ncols = max(len(probe.columns), 1)
        unnamed_n = sum(1 for c in probe.columns if _is_unnamed_col(c))
        if unnamed_n / float(ncols) > 0.28:
            df = _read_excel_guess_header(path, sheet)
        else:
            df = pd.read_excel(path, sheet_name=sheet, dtype=object, header=0)
    elif ext == ".csv":
        df = pd.read_csv(path, dtype=object, encoding="utf-8-sig", low_memory=False)
    else:
        raise ValueError(f"Unsupported file type: {ext}. Use .xlsx, .xlsm, .xls, or .csv")

    if not hasattr(df, "attrs") or df.attrs is None:
        df.attrs = {}
    prior = df.attrs.get(ATTR_READ_NOTES, [])
    notes = list(prior) if isinstance(prior, list) else []
    _sanitize_columns_inplace(df, notes)
    if os.environ.get("OPENAI_API_KEY"):
        df = _maybe_ai_rename_columns(df, notes, loc)

    if notes:
        df.attrs[ATTR_READ_NOTES] = notes
    return df
