"""API views for Arabic compliance dashboard (scoped per Dashboard pk)."""
from __future__ import annotations

import json
import re

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET, require_http_methods

from ai_excel_dashboard import _valid_obs_email, load_smtp_config, send_audit_observation_email_smtp
from arabic_compliance_dashboard.data import (
    dataframe_from_dashboard,
    is_ar_compliance_template,
    load_rows_from_dashboard,
    main_brand_logo_pack,
    resolve_brand_logo_company,
)
from arabic_compliance_dashboard.engine import (
    build_audit_plan_panel,
    build_summary,
    compute_aging,
    legal_details_from_rows,
    parse_query_params,
    selected_from_params,
)
from arabic_compliance_dashboard.generator import export_snapshot_html
from arabic_compliance_dashboard.pptx_export import build_legal_text_pptx
from reports_app.dashboard_workflow import (
    activate_company_for_dashboard,
    has_dashboard_list_perm,
    load_dashboard_cross_company,
)


def _resolve_ar_dashboard(request, pk: int):
    dashboard = load_dashboard_cross_company(request.user, pk)
    if not dashboard or not is_ar_compliance_template(dashboard.template_type):
        return None, JsonResponse({"error": "not_found"}, status=404)
    if not activate_company_for_dashboard(request, dashboard):
        return None, JsonResponse({"error": "forbidden"}, status=403)
    active = getattr(request, "active_company", None) or dashboard.company
    if not has_dashboard_list_perm(request.user, active):
        return None, JsonResponse({"error": "forbidden"}, status=403)
    return dashboard, None


def _rows_for(dashboard):
    return load_rows_from_dashboard(dashboard)


@login_required
@require_GET
def ar_api_summary(request, pk: int):
    dashboard, err = _resolve_ar_dashboard(request, pk)
    if err:
        return err
    rows = _rows_for(dashboard)
    selected = selected_from_params(parse_query_params(request.GET))
    return JsonResponse(build_summary(rows, selected))


@login_required
@require_GET
def ar_api_aging_summary(request, pk: int):
    dashboard, err = _resolve_ar_dashboard(request, pk)
    if err:
        return err
    ref = (request.GET.get("reference") or "").strip()
    if not ref:
        return JsonResponse({"error": "Missing reference date"}, status=400)
    date_source = (request.GET.get("aging_date_source") or "target").lower()
    rows = _rows_for(dashboard)
    selected = selected_from_params(parse_query_params(request.GET))
    out = compute_aging(
        rows,
        selected,
        ref,
        "modified" if date_source == "modified" else "target",
    )
    if out.get("error"):
        return JsonResponse({"error": out["error"]}, status=400)
    return JsonResponse(out)


@login_required
@require_http_methods(["GET", "POST"])
def ar_api_legal_text_details(request, pk: int):
    dashboard, err = _resolve_ar_dashboard(request, pk)
    if err:
        return err
    text = (request.GET.get("text") or "").strip()
    if not text and request.method == "POST":
        try:
            body = json.loads(request.body.decode("utf-8"))
            text = str(body.get("text") or "").strip()
        except Exception:
            text = ""
    if not text:
        return JsonResponse({"error": "Not found"}, status=404)
    rows = _rows_for(dashboard)
    rec = legal_details_from_rows(rows, text)
    if not rec:
        return JsonResponse({"error": "Not found"}, status=404)
    return JsonResponse(rec)


@login_required
@require_GET
def ar_api_legal_text_row_images(request, pk: int):
    dashboard, err = _resolve_ar_dashboard(request, pk)
    if err:
        return err
    return JsonResponse({"images": []})


@login_required
@require_http_methods(["POST", "OPTIONS"])
def ar_api_send_legal_text_email(request, pk: int):
    if request.method == "OPTIONS":
        return JsonResponse({}, status=204)
    dashboard, err = _resolve_ar_dashboard(request, pk)
    if err:
        return err
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "bad_json"}, status=400)
    text = str(data.get("text") or "").strip()
    to_addr = str(data.get("to") or "").strip()
    if not to_addr:
        rows = _rows_for(dashboard)
        rec = legal_details_from_rows(rows, text)
        to_addr = (rec or {}).get("recipient_email") or ""
    if not _valid_obs_email(to_addr):
        return JsonResponse({"error": "bad_email"}, status=400)
    if not text:
        return JsonResponse({"error": "bad_text"}, status=400)
    cfg = load_smtp_config()
    if not cfg:
        return JsonResponse({"error": "smtp_not_configured"}, status=503)
    try:
        send_audit_observation_email_smtp(cfg, to_addr=to_addr, observation=text)
    except Exception as exc:
        return JsonResponse({"error": str(exc)[:500]}, status=500)
    return JsonResponse({"ok": True, "to": to_addr})


@login_required
@require_http_methods(["POST", "OPTIONS"])
def ar_api_export_legal_text_pptx(request, pk: int):
    if request.method == "OPTIONS":
        return JsonResponse({}, status=204)
    dashboard, err = _resolve_ar_dashboard(request, pk)
    if err:
        return err
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "bad_json"}, status=400)
    text = str(data.get("text") or "").strip()
    if not text:
        return JsonResponse({"error": "missing_text"}, status=400)
    fields = data.get("fields") or []
    if not fields:
        rows = _rows_for(dashboard)
        rec = legal_details_from_rows(rows, text)
        fields = (rec or {}).get("fields") or []
    raw = build_legal_text_pptx(text, fields)
    safe = re.sub(r"[^\w\-]+", "_", text[:40]) or "legal-text"
    resp = HttpResponse(
        raw,
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
    resp["Content-Disposition"] = f'attachment; filename="{safe}.pptx"'
    return resp


@login_required
@require_GET
def ar_api_export_dashboard_html(request, pk: int):
    dashboard, err = _resolve_ar_dashboard(request, pk)
    if err:
        return err
    df = dataframe_from_dashboard(dashboard)
    brand_logos, default_brand_code = main_brand_logo_pack(dashboard.company)
    html_out = export_snapshot_html(
        df,
        dashboard_id=dashboard.pk,
        brand_logos=brand_logos,
        default_brand_code=default_brand_code,
    )
    resp = HttpResponse(html_out, content_type="text/html; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="dashboard-export.html"'
    return resp


@login_required
@require_GET
def ar_api_brand_logo(request, pk: int):
    dashboard, err = _resolve_ar_dashboard(request, pk)
    if err:
        return err

    company = dashboard.company
    if not company:
        return HttpResponse(status=204)

    from audit_app.company_access import tenant_root

    code = (request.GET.get("code") or "").strip()
    target = resolve_brand_logo_company(company, code or None)
    root = tenant_root(company)
    logo_field = target.logo if getattr(target, "logo", None) else root.logo
    if not logo_field:
        return HttpResponse(status=204)
    try:
        import mimetypes

        mime = mimetypes.guess_type(logo_field.name)[0] or "image/png"
        return HttpResponse(logo_field.open("rb").read(), content_type=mime)
    except Exception:
        return HttpResponse(status=204)


@login_required
@require_GET
def ar_api_audit_plan_panel(request, pk: int):
    dashboard, err = _resolve_ar_dashboard(request, pk)
    if err:
        return err
    rows = _rows_for(dashboard)
    selected = selected_from_params(parse_query_params(request.GET))
    return JsonResponse(build_audit_plan_panel(rows, selected))
