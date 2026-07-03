import pandas as pd

from ai_excel_dashboard import _json_safe_obs_date_cell, resolve_audit_observation_columns


def test_json_safe_obs_date_cell_normalizes_common_formats():
    assert _json_safe_obs_date_cell(45508) == 45508
    assert _json_safe_obs_date_cell("45508") == 45508
    assert _json_safe_obs_date_cell("15/03/2024") == "2024-03-15"
    assert _json_safe_obs_date_cell(pd.Timestamp("2024-06-01")) == "2024-06-01"
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
