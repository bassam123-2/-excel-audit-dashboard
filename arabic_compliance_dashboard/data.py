"""Load dashboard rows and tenant validation for Arabic compliance template."""
from __future__ import annotations

import json
from typing import Any

import pandas as pd

from audit_app.models import Dashboard

from .schema import (
    BLANK,
    CANONICAL_NAMES,
    TEMPLATE_CODE,
    normalize_dataframe,
    rows_from_dataframe,
    validate_schema,
)


def is_ar_compliance_template(template_type: str | None) -> bool:
    return (template_type or "") == TEMPLATE_CODE


def dataframe_from_dashboard(dashboard: Dashboard) -> pd.DataFrame:
    session = dashboard.upload_session
    if not session or not session.raw_data_json:
        raise ValueError("No stored data for this dashboard.")
    raw = json.loads(session.raw_data_json)
    if isinstance(raw, list):
        entry = raw[0]
    else:
        entry = raw
    return pd.DataFrame(entry["data"], columns=entry["columns"])


def load_rows_from_dashboard(dashboard: Dashboard) -> list[dict[str, str]]:
    df = dataframe_from_dashboard(dashboard)
    return rows_from_dataframe(normalize_dataframe(df))


def brand_logo_pack(company) -> tuple[dict[str, str], str | None]:
    """Flat code→data-uri map for tenant root and subsidiaries; default is root code."""
    if not company:
        return {}, None
    from audit_app.company_access import tenant_root
    from ai_excel_dashboard import _logo_catalog_company_key, build_company_logo_catalog

    root = tenant_root(company)
    root_key = _logo_catalog_company_key(root.code)
    if not root_key:
        return {}, None

    catalog = build_company_logo_catalog(root)
    logos: dict[str, str] = {}
    for key, uri in (catalog.get("companies") or {}).items():
        if key and uri:
            logos[key] = uri
    for composite, uri in (catalog.get("subcompanies") or {}).items():
        if not uri or "|" not in composite:
            continue
        _, sub_key = composite.rsplit("|", 1)
        if sub_key and sub_key not in logos:
            logos[sub_key] = uri
    return logos, root_key


def resolve_brand_logo_company(company, code: str | None):
    """Return the Company record whose logo matches *code* (subsidiary or tenant root)."""
    from audit_app.company_access import active_subsidiaries_of, tenant_root
    from ai_excel_dashboard import _logo_catalog_company_key

    root = tenant_root(company)
    if not code:
        return root
    wanted = _logo_catalog_company_key(code)
    root_key = _logo_catalog_company_key(root.code)
    if not wanted or wanted == root_key:
        return root
    for sub in active_subsidiaries_of(root):
        keys = {
            _logo_catalog_company_key(sub.code),
            _logo_catalog_company_key(sub.name),
        }
        keys.update(_logo_catalog_company_key(label) for label in sub.accepted_excel_names())
        keys.discard("")
        if wanted in keys:
            return sub
    return root


def main_brand_logo_pack(company) -> tuple[dict[str, str], str | None]:
    """Tenant root + subsidiary logos for the dashboard header."""
    return brand_logo_pack(company)


def validate_ar_companies_for_tenant(df: pd.DataFrame, active_company, locale: str = "ar") -> None:
    """Optional tenant check when holding/subsidiary columns exist."""
    from audit_app.company_access import (
        validate_excel_company_for_tenant,
        validate_excel_subcompanies_for_tenant,
    )

    normalized = normalize_dataframe(df)
    holding_col = CANONICAL_NAMES["holding_company"]
    sub_col = CANONICAL_NAMES["subsidiary_company"]

    if holding_col in normalized.columns:
        names = {
            str(x).strip()
            for x in normalized[holding_col].dropna().unique()
            if str(x).strip() and str(x).strip() != BLANK
        }
        if names:
            validate_excel_company_for_tenant(active_company, names, locale=locale)

    if sub_col in normalized.columns:
        names = {
            str(x).strip()
            for x in normalized[sub_col].dropna().unique()
            if str(x).strip() and str(x).strip() != BLANK
        }
        if names:
            validate_excel_subcompanies_for_tenant(active_company, names, locale=locale)


def prepare_upload_dataframe(df: pd.DataFrame, locale: str = "ar") -> pd.DataFrame:
    validate_schema(df, locale=locale)
    return normalize_dataframe(df)


def minimal_audit_payload(*, report_id: str, df: pd.DataFrame) -> dict[str, Any]:
    return {
        "report_id": report_id,
        "report_version": "ar_compliance_1",
        "rows": len(df),
        "columns": len(df.columns),
        "audit_observations": {"rows": []},
    }
