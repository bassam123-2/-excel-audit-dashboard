"""Integration tests for ar_compliance upload and API data serving."""

from __future__ import annotations

import json
from io import BytesIO

import pandas as pd
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from audit_app.company_access import SESSION_ACTIVE_COMPANY_KEY
from audit_app.models import COMPANY_KIND_MAIN, Dashboard, DashboardStatus
from tests.factories import make_membership, make_user


def _sample_ar_compliance_xlsx() -> SimpleUploadedFile:
    """Workbook shaped like compliance-register-template-new.xlsx."""
    df = pd.DataFrame(
        [
            {
                "تصنيف المخاطر الكامنة": "عالي",
                "تصنيف المخاطر المتبقية": "متوسط",
                "الحالة": "مفتوح",
                "الإدارة المسؤولة": "الامتثال",
                "المشرع": "وزارة التجارة",
                "اسم النظام": "نظام الشركات",
                "الهيئة التابعة": "هيئة السوق المالية",
                "اللائحة": "لائحة حوكمة الشركات",
                "النص النظامي": "يجب على الشركة الإفصاح عن...",
                "حالة الالتزام": "غير ملتزم",
                "فئة الضوابط الرقابية": "رقابي",
                "السنوات": "2025",
                "تاريخ التصحيح المستهدف": "2025-06-30",
                "تاريخ التصحيح المعدل": None,
                "الشركة القابضة": "BTC",
                "الشركة التابعة": None,
                "email": "user@example.com",
                "مالك المهمة / مالك الإجراء": "أحمد",
                "الشخص المسؤول": "سارة",
                "الخطة التصحيحية": "إعداد خطة تصحيح",
            },
            {
                "تصنيف المخاطر الكامنة": "متوسط",
                "تصنيف المخاطر المتبقية": "منخفض",
                "الحالة": "مغلق",
                "الإدارة المسؤولة": "المالية",
                "المشرع": "هيئة الزكاة",
                "اسم النظام": "نظام ضريبة القيمة المضافة",
                "الهيئة التابعة": "هيئة الزكاة والضريبة",
                "اللائحة": "اللائحة التنفيذية",
                "النص النظامي": "يجب تقديم الإقرار...",
                "حالة الالتزام": "ملتزم",
                "فئة الضوابط الرقابية": "وقائي",
                "السنوات": "2024",
                "تاريخ التصحيح المستهدف": "2024-12-31",
                "تاريخ التصحيح المعدل": "2025-01-15",
                "الشركة القابضة": "BTC",
                "الشركة التابعة": None,
                "email": None,
                "مالك المهمة / مالك الإجراء": "خالد",
                "الشخص المسؤول": "نورة",
                "الخطة التصحيحية": None,
            },
        ]
    )
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="سجل الالتزام الموحد", index=False)
    buffer.seek(0)
    return SimpleUploadedFile(
        "compliance-register-template-new.xlsx",
        buffer.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@pytest.mark.django_db
def test_ar_compliance_upload_serve_and_summary_api(admin_client, btc_company):
    btc_company.company_kind = COMPANY_KIND_MAIN
    btc_company.save(update_fields=["company_kind"])
    session = admin_client.session
    session[SESSION_ACTIVE_COMPANY_KEY] = btc_company.pk
    session.save()

    upload = _sample_ar_compliance_xlsx()
    response = admin_client.post(
        reverse("analyze"),
        {
            "dashboard_name": "AR Compliance Test",
            "icon": "bi-bar-chart-line-fill",
            "description": "Test",
            "template_type": "CD",
            "file1": upload,
        },
        follow=False,
    )
    assert response.status_code == 302, response.content[:500]

    dashboard = Dashboard.objects.filter(name="AR Compliance Test").first()
    assert dashboard is not None
    assert dashboard.template_type == "CD"
    assert dashboard.upload_session is not None
    assert dashboard.upload_session.raw_data_json

    raw = json.loads(dashboard.upload_session.raw_data_json)
    assert len(raw["data"]) == 2

    serve_url = reverse("dashboard_serve", args=[dashboard.pk])
    serve_resp = admin_client.get(f"{serve_url}?nocache=1")
    assert serve_resp.status_code == 200
    html = serve_resp.content.decode()
    assert "snapshot-pack" in html
    assert "عالي" in html or "window.__AR_DASHBOARD__" in html

    summary_url = reverse("ar_api_summary", args=[dashboard.pk])
    summary_resp = admin_client.get(summary_url)
    assert summary_resp.status_code == 200, summary_resp.content[:300]
    payload = summary_resp.json()
    assert payload["total"] == 2
    assert "الحالة" in payload["groups"]
    assert any(item["key"] == "مفتوح" for item in payload["groups"]["الحالة"])


@pytest.mark.django_db
def test_ar_compliance_summary_api_with_uploader_membership(client, btc_company):
    btc_company.company_kind = COMPANY_KIND_MAIN
    btc_company.save(update_fields=["company_kind"])

    user = make_user("ar_uploader", email="ar_uploader@example.com")
    make_membership(user, btc_company, can_upload=True, can_view=True)
    client.force_login(user)
    session = client.session
    session[SESSION_ACTIVE_COMPANY_KEY] = btc_company.pk
    session.save()

    upload = _sample_ar_compliance_xlsx()
    response = client.post(
        reverse("analyze"),
        {
            "dashboard_name": "AR Membership Test",
            "icon": "bi-bar-chart-line-fill",
            "description": "",
            "template_type": "CD",
            "file1": upload,
        },
    )
    assert response.status_code == 302

    dashboard = Dashboard.objects.get(name="AR Membership Test")
    summary_url = reverse("ar_api_summary", args=[dashboard.pk])
    summary_resp = client.get(summary_url)
    assert summary_resp.status_code == 200, summary_resp.content[:300]
    assert summary_resp.json()["total"] == 2
