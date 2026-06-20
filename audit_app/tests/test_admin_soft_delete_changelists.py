"""Ensure soft-delete admin changelists load without filter errors."""
from __future__ import annotations

import pytest
from django.contrib import admin
from django.urls import reverse

from audit_app.admin_soft_delete import SoftDeleteAdminMixin


def _soft_delete_admin_models():
    for model, model_admin in admin.site._registry.items():
        if isinstance(model_admin, SoftDeleteAdminMixin) and hasattr(model, "is_deleted"):
            yield model, model_admin


_SOFT_DELETE_ADMIN_CASES = list(_soft_delete_admin_models())


@pytest.mark.django_db
@pytest.mark.parametrize(
    "model,model_admin",
    _SOFT_DELETE_ADMIN_CASES,
    ids=[model._meta.label_lower for model, _ in _SOFT_DELETE_ADMIN_CASES],
)
def test_soft_delete_admin_changelist_loads(admin_client, model, model_admin):
    changelist_name = f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist"
    base_url = reverse(changelist_name)
    for query in ("", "?deleted=active", "?deleted=deleted", "?deleted=all"):
        response = admin_client.get(f"{base_url}{query}", follow=True)
        assert response.status_code == 200, (
            f"{model._meta.label} changelist failed for {query!r}: "
            f"{getattr(response, 'status_code', '?')}"
        )


@pytest.mark.django_db
def test_user_admin_deleted_filter_changelist_loads(admin_client):
    url = reverse("admin:auth_user_changelist")
    for query in ("", "?deleted=active", "?deleted=deleted", "?deleted=all"):
        response = admin_client.get(f"{url}{query}", follow=True)
        assert response.status_code == 200
