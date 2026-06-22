"""Company admin parent-field autocomplete tests."""

from __future__ import annotations

import pytest
from django.urls import reverse

from audit_app.models import COMPANY_KIND_MAIN, COMPANY_KIND_SUBSIDIARY, Company


@pytest.mark.django_db
def test_parent_autocomplete_lists_main_companies_only(admin_client, btc_company):
    main = Company.objects.create(code="MAINCO", name="Main Co", company_kind=COMPANY_KIND_MAIN)
    subsidiary = Company.objects.create(
        code="SUBCO",
        name="Sub Co",
        company_kind=COMPANY_KIND_SUBSIDIARY,
        parent=btc_company,
    )

    url = reverse("admin:autocomplete")
    response = admin_client.get(
        url,
        {
            "term": "",
            "app_label": "audit_app",
            "model_name": "company",
            "field_name": "parent",
        },
    )

    assert response.status_code == 200
    result_ids = {item["id"] for item in response.json()["results"]}
    assert str(main.pk) in result_ids
    assert str(btc_company.pk) in result_ids
    assert str(subsidiary.pk) not in result_ids


@pytest.mark.django_db
def test_parent_autocomplete_excludes_current_company(admin_client, btc_company):
    main = Company.objects.create(code="MAINCO", name="Main Co", company_kind=COMPANY_KIND_MAIN)

    url = reverse("admin:autocomplete")
    response = admin_client.get(
        url,
        {
            "term": "",
            "app_label": "audit_app",
            "model_name": "company",
            "field_name": "parent",
            "exclude_pk": str(btc_company.pk),
        },
    )

    assert response.status_code == 200
    result_ids = {item["id"] for item in response.json()["results"]}
    assert str(btc_company.pk) not in result_ids
    assert str(main.pk) in result_ids


@pytest.mark.django_db
def test_parent_autocomplete_excludes_self_from_change_referer(admin_client, btc_company):
    main = Company.objects.create(code="MAINCO", name="Main Co", company_kind=COMPANY_KIND_MAIN)

    url = reverse("admin:autocomplete")
    change_url = reverse("admin:audit_app_company_change", args=[btc_company.pk])
    response = admin_client.get(
        url,
        {
            "term": "",
            "app_label": "audit_app",
            "model_name": "company",
            "field_name": "parent",
        },
        HTTP_REFERER=f"http://testserver{change_url}",
    )

    assert response.status_code == 200
    result_ids = {item["id"] for item in response.json()["results"]}
    assert str(btc_company.pk) not in result_ids
    assert str(main.pk) in result_ids


@pytest.mark.django_db
def test_company_change_form_parent_field_has_exclude_pk(admin_client, btc_company):
    url = reverse("admin:audit_app_company_change", args=[btc_company.pk])
    response = admin_client.get(url)
    assert response.status_code == 200
    html = response.content.decode()
    assert f'data-exclude-pk="{btc_company.pk}"' in html
