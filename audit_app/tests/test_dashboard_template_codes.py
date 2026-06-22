"""Tests for built-in dashboard template type codes and seeding."""

from __future__ import annotations

import pytest

from audit_app.dashboard_template_codes import (
    TEMPLATE_CODE_CD,
    TEMPLATE_CODE_IAD,
    seed_dashboard_template_types,
)
from audit_app.models import DashboardTemplateType


@pytest.mark.django_db
def test_seed_dashboard_template_types_creates_built_in_records():
    seed_dashboard_template_types()

    iad = DashboardTemplateType.objects.get(code=TEMPLATE_CODE_IAD)
    cd = DashboardTemplateType.objects.get(code=TEMPLATE_CODE_CD)

    assert iad.name == "Internal Audit Dashboard"
    assert cd.name == "Compliance Dashboard"
    assert iad.is_active is True
    assert cd.is_active is True
