from django.test import Client


def test_version_endpoint_returns_payload():
    client = Client()
    response = client.get("/api/version")
    assert response.status_code == 200
    payload = response.json()
    assert "report_version" in payload
    assert "module_file" in payload


def test_index_page_renders():
    client = Client()
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response["Content-Type"]
