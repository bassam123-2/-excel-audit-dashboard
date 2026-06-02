from __future__ import annotations

from typing import Any

import pandas as pd

from ai_excel_dashboard import (
    _audit_observation_row_is_usable,
    build_audit_observation_payload,
    build_company_logo_catalog,
    build_detected_profile,
    resolve_audit_observation_columns,
)


def resolve_columns(df: pd.DataFrame) -> dict[str, str] | None:
    return resolve_audit_observation_columns(df)


def usable_observation_rows(df: pd.DataFrame, colmap: dict[str, str]) -> pd.DataFrame:
    if df.empty:
        return df
    mask = df.apply(lambda row: _audit_observation_row_is_usable(row, colmap), axis=1)
    return df.loc[mask].copy()


def build_observation_payload(
    df: pd.DataFrame,
    colmap: dict[str, str],
    *,
    locale: str,
    max_rows: int = 8000,
    max_options: int = 200,
) -> dict[str, Any]:
    return build_audit_observation_payload(
        df, colmap, locale=locale, max_rows=max_rows, max_options=max_options
    )


def build_logo_catalog() -> dict[str, Any]:
    return build_company_logo_catalog()


def build_profile(df: pd.DataFrame) -> dict[str, Any]:
    return build_detected_profile(df)
