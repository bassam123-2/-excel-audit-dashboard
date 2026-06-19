import pandas as pd

from ai_excel_dashboard import resolve_audit_observation_columns


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
