"""Dashboard template type codes — single source of truth."""

from __future__ import annotations

TEMPLATE_CODE_IAD = "IAD"
TEMPLATE_CODE_CD = "CD"

LEGACY_TEMPLATE_CODE_IAD = "ai"
LEGACY_TEMPLATE_CODE_CD = "ar_compliance"

DEFAULT_DASHBOARD_TEMPLATE_CODE = TEMPLATE_CODE_IAD

LEGACY_CODE_MAP: dict[str, str] = {
    LEGACY_TEMPLATE_CODE_IAD: TEMPLATE_CODE_IAD,
    LEGACY_TEMPLATE_CODE_CD: TEMPLATE_CODE_CD,
}

TEMPLATE_TYPE_SEEDS: list[dict] = [
    {
        "code": TEMPLATE_CODE_IAD,
        "name": "Internal Audit Dashboard",
        "description": "AI-built internal audit analytics dashboard.",
        "icon": "bi-stars",
        "sort_order": 1,
    },
    {
        "code": TEMPLATE_CODE_CD,
        "name": "Compliance Dashboard",
        "description": "Regulatory compliance dashboard with filters, aging, and legal texts.",
        "icon": "bi-clipboard2-data-fill",
        "sort_order": 2,
    },
]


def seed_dashboard_template_types(apps=None) -> None:
    """Create or update built-in dashboard template types (migration + setup)."""
    if apps is None:
        from audit_app.models import Dashboard, DashboardTemplateType, UploadSession
    else:
        DashboardTemplateType = apps.get_model("audit_app", "DashboardTemplateType")
        Dashboard = apps.get_model("audit_app", "Dashboard")
        UploadSession = apps.get_model("audit_app", "UploadSession")

    for legacy_code, new_code in LEGACY_CODE_MAP.items():
        DashboardTemplateType.objects.filter(code=legacy_code).update(code=new_code)

    Dashboard.objects.filter(template_type=LEGACY_TEMPLATE_CODE_IAD).update(
        template_type=TEMPLATE_CODE_IAD
    )
    Dashboard.objects.filter(template_type=LEGACY_TEMPLATE_CODE_CD).update(
        template_type=TEMPLATE_CODE_CD
    )
    UploadSession.objects.filter(mode=LEGACY_TEMPLATE_CODE_IAD).update(mode=TEMPLATE_CODE_IAD)
    UploadSession.objects.filter(mode=LEGACY_TEMPLATE_CODE_CD).update(mode=TEMPLATE_CODE_CD)

    for seed in TEMPLATE_TYPE_SEEDS:
        code = seed["code"]
        defaults = {key: value for key, value in seed.items() if key != "code"}
        defaults["is_active"] = True
        DashboardTemplateType.objects.update_or_create(code=code, defaults=defaults)
