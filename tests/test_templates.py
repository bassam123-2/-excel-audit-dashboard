"""Template markup tests."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.unit
def test_login_template_only_disables_submit_button():
    html = (Path(__file__).resolve().parents[1] / "templates/accounts/login.html").read_text(
        encoding="utf-8"
    )
    assert "btn.disabled = true" in html
    assert "input:not([type=\"hidden\"])" not in html


@pytest.mark.unit
def test_login_template_loading_state():
    html = (Path(__file__).resolve().parents[1] / "templates/accounts/login.html").read_text(
        encoding="utf-8"
    )
    assert "btn-spinner" in html
    assert "is-loading" in html
    assert "data-loading-text" in html


@pytest.mark.unit
def test_dashboard_list_undo_toast_markup():
    html = (
        Path(__file__).resolve().parents[1] / "templates/reports_app/dashboard_list.html"
    ).read_text(encoding="utf-8")
    assert "undo-toast" in html
    assert "js-super-delete-form" in html
    assert "dl_undo_btn" in html or "btn-undo" in html
