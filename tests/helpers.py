"""Shared helpers for integration tests."""
from __future__ import annotations

from django.test import Client

from audit_app.models import Company


def login_client(client: Client, username: str, password: str = "Test@1234") -> None:
    response = client.post("/login/", {"username": username, "password": password})
    assert response.status_code in (302, 200)


def login_and_select_company(
    client: Client,
    username: str,
    company: Company,
    password: str = "Test@1234",
) -> None:
    login_client(client, username, password)
    client.post("/select-company/", {"company_id": company.pk})
