import pytest
from django.test import Client


@pytest.mark.django_db
def test_version_endpoint_returns_payload():
    client = Client()
    response = client.get("/api/version")
    assert response.status_code == 200
    payload = response.json()
    assert "report_version" in payload
    assert "module_file" in payload


@pytest.mark.django_db
def test_index_page_renders():
    client = Client()
    response = client.get("/")
    # Upload page requires authentication; unauthenticated users go to login.
    assert response.status_code == 302
    assert response.url.startswith("/login/")
