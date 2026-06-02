from __future__ import annotations

import base64

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ai_excel_dashboard import (
    _valid_obs_email,
    load_smtp_config,
    parse_audit_plan_pptx_bytes,
    send_audit_observation_email_smtp,
)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def send_obs_email(request):
    if request.method == "OPTIONS":
        return JsonResponse({}, status=204)
    try:
        data = __import__("json").loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "bad_json"}, status=400)
    to_addr = str(data.get("to", "")).strip()
    observation = str(data.get("observation", "")).strip()
    if not _valid_obs_email(to_addr):
        return JsonResponse({"ok": False, "error": "bad_email"}, status=400)
    if not observation or len(observation) > 8000:
        return JsonResponse({"ok": False, "error": "bad_observation"}, status=400)
    cfg = load_smtp_config()
    if not cfg:
        return JsonResponse({"ok": False, "error": "smtp_not_configured"}, status=503)
    try:
        send_audit_observation_email_smtp(cfg, to_addr=to_addr, observation=observation)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)[:500]}, status=500)
    return JsonResponse({"ok": True})


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def parse_audit_plan_pptx(request):
    if request.method == "OPTIONS":
        return JsonResponse({}, status=204)
    try:
        data = __import__("json").loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "bad_json", "rows": []}, status=400)
    b64 = str(data.get("pptx_b64", "")).strip()
    if not b64:
        return JsonResponse(
            {"ok": False, "error": "missing_pptx_b64", "rows": []}, status=400
        )
    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception:
        return JsonResponse({"ok": False, "error": "bad_b64", "rows": []}, status=400)
    rows, err = parse_audit_plan_pptx_bytes(raw)
    if err:
        return JsonResponse({"ok": False, "error": err, "rows": []}, status=400)
    return JsonResponse({"ok": True, "rows": rows})
