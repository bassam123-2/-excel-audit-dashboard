from __future__ import annotations

from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_GET

import ai_excel_dashboard as _ai_excel_dashboard_mod

from .services.report_generation import (
    build_response_for_request,
    upload_form_html,
    version_payload,
)


@require_GET
def index(request):
    locale = request.GET.get("lang", "en")
    return HttpResponse(
        upload_form_html(locale), content_type="text/html; charset=utf-8"
    )


@require_GET
def analyze_get(request):
    return redirect("/")


def analyze(request):
    if request.method == "GET":
        return redirect("/")
    if request.method == "POST":
        return build_response_for_request(request)
    return HttpResponse("Method not allowed", status=405)


@require_GET
def api_version(request):
    module_file = str(getattr(_ai_excel_dashboard_mod, "__file__", ""))
    return JsonResponse(version_payload(module_file))
