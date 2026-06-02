import pandas as pd

from audit_app.services.audit_processing import resolve_columns


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
    colmap = resolve_columns(df)
    assert colmap is not None
    assert colmap["audit_year"] == "Audit Year"
