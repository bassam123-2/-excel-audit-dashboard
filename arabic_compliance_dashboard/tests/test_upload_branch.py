"""Regression: AI template upload path unchanged."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from arabic_compliance_dashboard.schema import TEMPLATE_CODE


def test_store_upload_branches_ar_before_ai(monkeypatch):
    """ar_compliance must not call generate_finance_report."""
    from reports_app.services import report_generation as rg

    called = {"finance": False, "ar": False}

    def fake_ar(*args, **kwargs):
        called["ar"] = True
        dash = MagicMock()
        dash.pk = 1
        return dash

    def fake_finance(*args, **kwargs):
        called["finance"] = True
        return ("html", {})

    monkeypatch.setattr(rg, "_store_ar_compliance_upload", fake_ar)
    monkeypatch.setattr(rg, "generate_finance_report", fake_finance)
    monkeypatch.setattr(rg, "excel_uploads_from_request", lambda r: [MagicMock(name="f.xlsx")])
    monkeypatch.setattr(
        "audit_app.company_access.resolve_tenant_company",
        lambda c: MagicMock(pk=1),
    )

    request = MagicMock()
    request.session = {"ui_lang": "en"}
    request.user.is_authenticated = True
    request.FILES = {}
    request.active_company = MagicMock(pk=1)

    rg.store_upload_to_db(request, "Test", "bi-bar-chart-line-fill", template_type=TEMPLATE_CODE)
    assert called["ar"] is True
    assert called["finance"] is False


def test_is_ar_compliance_template():
    from arabic_compliance_dashboard.data import is_ar_compliance_template

    assert is_ar_compliance_template("CD") is True
    assert is_ar_compliance_template("IAD") is False
