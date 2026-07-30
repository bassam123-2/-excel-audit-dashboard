"""Tests for per-viewer attachment kind filtering in served dashboard HTML."""
from __future__ import annotations

from django.test import SimpleTestCase

from reports_app.services.report_generation import filter_dashboard_html_attachments


class FilterDashboardHtmlAttachmentsTests(SimpleTestCase):
    def test_strips_denied_payload_keys_and_toggles(self):
        html = (
            "<html><body>"
            '<label class="audit-obs-aging-toggle">'
            '<input type="checkbox" id="audit-deck-attach-cb" '
            'aria-controls="audit-deck-modal" aria-haspopup="dialog" />'
            '<span id="audit-deck-attach-label"></span>'
            "</label>"
            '<label class="audit-obs-aging-toggle">'
            '<input type="checkbox" id="audit-high-risk-cb" '
            'aria-controls="audit-deck-modal" aria-haspopup="dialog" />'
            '<span id="audit-high-risk-label"></span>'
            "</label>"
            "<script>"
            'const payload = {"embedded_slide_deck": {"files": ["SECRET_DECK"]},'
            ' "embedded_high_risk_slide_deck": {"files": ["SECRET_HR"]},'
            ' "ui": {"x": 1}};'
            "</script>"
            "</body></html>"
        )
        out = filter_dashboard_html_attachments(html, {"deck"})
        self.assertIn("SECRET_DECK", out)
        self.assertNotIn("SECRET_HR", out)
        self.assertIn('id="audit-deck-attach-cb"', out)
        self.assertNotIn('id="audit-high-risk-cb"', out)

    def test_allows_all_when_all_kinds_granted(self):
        html = (
            'const payload = {"embedded_slide_deck": {"a": 1},'
            ' "embedded_high_risk_slide_deck": {"b": 2}};'
        )
        out = filter_dashboard_html_attachments(
            html,
            {
                "deck",
                "highRisk",
                "tgaViolations",
                "missingVehicle",
                "internalAuditQuarterly",
                "specialAssignment",
                "accApprovedMoM",
                "internalAuditDetailed",
            },
        )
        compact = out.replace(" ", "")
        self.assertIn('"a":1', compact)
        self.assertIn('"b":2', compact)

    def test_empty_allowed_strips_all_attachments(self):
        html = (
            'const payload = {"embedded_slide_deck": {"files": ["X"]},'
            ' "ui": {}};'
        )
        out = filter_dashboard_html_attachments(html, set())
        self.assertNotIn("X", out)
        self.assertIn('"embedded_slide_deck": null', out)
