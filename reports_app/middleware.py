from __future__ import annotations

from ai_excel_dashboard import REPORT_VERSION


class DashboardVersionHeaderMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["X-Dashboard-Version"] = REPORT_VERSION
        return response
