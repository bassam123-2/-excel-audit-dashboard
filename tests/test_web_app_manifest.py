"""PWA web app manifest is served outside /static/ to avoid VPS JSON 403."""
from __future__ import annotations

import json
from pathlib import Path

from django.test import Client, TestCase
from django.urls import reverse


class WebAppManifestTests(TestCase):
    def test_manifest_returns_200_with_webmanifest_type(self):
        client = Client()
        response = client.get(reverse("web_app_manifest"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/manifest+json", response["Content-Type"])
        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload.get("name"), "Audit Dashboard")
        self.assertTrue(payload.get("icons"))

    def test_templates_link_django_manifest_url_not_static_json(self):
        base = Path(__file__).resolve().parents[1] / "templates" / "base.html"
        text = base.read_text(encoding="utf-8")
        self.assertIn("web_app_manifest", text)
        self.assertNotIn("static 'manifest.json'", text)
