import pandas as pd

from ai_excel_dashboard import _json_safe_obs_date_cell, resolve_audit_observation_columns


def test_json_safe_obs_date_cell_normalizes_common_formats():
    assert _json_safe_obs_date_cell(45508) == 45508
    assert _json_safe_obs_date_cell("45508") == 45508
    assert _json_safe_obs_date_cell("15/03/2024") == "2024-03-15"
    assert _json_safe_obs_date_cell(pd.Timestamp("2024-06-01")) == "2024-06-01"
    assert _json_safe_obs_date_cell(1627603200000.0) == "2021-07-30"
    assert _json_safe_obs_date_cell(None) is None
    assert _json_safe_obs_date_cell("") is None


def test_resolve_columns_minimum_aliases():
    df = pd.DataFrame(
        {
            "Audit Year": [2025],
            "Department": ["IT"],
            "Audit Cycle/ Department": ["Cycle A"],
            "IA Status": ["Open"],
            "Observation Name": ["Missing control"],
        }
    )
    colmap = resolve_audit_observation_columns(df)
    assert colmap is not None
    assert colmap["audit_year"] == "Audit Year"


def _minimal_audit_df(**extra_columns):
    base = {
        "Audit Year": [2025],
        "Department": ["IT"],
        "Audit Cycle/ Department": ["Cycle A"],
        "IA Status": ["Open Not Due"],
        "Observation Name": ["Observation 1"],
    }
    base.update(extra_columns)
    return pd.DataFrame(base)


def test_resolve_columns_implementation_due_date():
    df = _minimal_audit_df(**{"Implementation Due Date": ["2025-06-01"]})
    colmap = resolve_audit_observation_columns(df)
    assert colmap is not None
    assert colmap["implementation_due"] == "Implementation Due Date"


def test_resolve_columns_revised_date_starts_with_prefix():
    df = _minimal_audit_df(**{"Revised Date Q2": ["2025-07-01"]})
    colmap = resolve_audit_observation_columns(df)
    assert colmap is not None
    assert colmap["revised_date"] == "Revised Date Q2"


def test_resolve_columns_target_revised_date_not_mapped_as_revised():
    df = _minimal_audit_df(**{"Target Revised Date": ["2025-08-01"]})
    colmap = resolve_audit_observation_columns(df)
    assert colmap is not None
    assert "revised_date" not in colmap
