from __future__ import annotations

import sys
from pathlib import Path
import shutil

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

import ai_excel_dashboard as _ai_excel_dashboard_mod

# web_strings.py lives at the project root
_BASE_DIR = str(Path(__file__).resolve().parents[1])
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)
from web_strings import get_ui  # noqa: E402

from audit_app.models import Dashboard, DashboardReview, DashboardTemplateType, ICON_CHOICES
from .services.report_generation import (
    html_no_cache_response,
    version_payload,
    generate_from_db_data,
    inject_dashboard_reviews_api,
    inject_web_mail_api,
    report_locale_for_dashboard,
    store_upload_to_db,
)


# ── Permission helpers ────────────────────────────────────────────────


def _has_upload_perm(user) -> bool:
    return user.is_staff or user.is_superuser or user.has_perm("audit_app.can_upload_files")


def _has_view_perm(user) -> bool:
    return (
        user.is_staff
        or user.is_superuser
        or user.has_perm("audit_app.can_view_dashboards")
        or user.has_perm("audit_app.can_upload_files")
    )


def _has_delete_perm(user) -> bool:
    return (
        user.is_staff
        or user.is_superuser
        or user.has_perm("audit_app.can_delete_dashboards")
    )


def _cleanup_dashboard_files(dashboard: Dashboard) -> None:
    """Remove cached HTML and uploaded deck files for a dashboard."""
    media_root = Path(settings.MEDIA_ROOT)
    dashboards_dir = media_root / "dashboards"
    if dashboards_dir.is_dir():
        for cache_file in dashboards_dir.glob(f"{dashboard.pk}_*.html"):
            try:
                cache_file.unlink()
            except OSError:
                pass
    if dashboard.html_file:
        html_path = media_root / dashboard.html_file
        if html_path.is_file():
            try:
                html_path.unlink()
            except OSError:
                pass
    if dashboard.report_id:
        decks_dir = media_root / "decks" / dashboard.report_id
        if decks_dir.is_dir():
            shutil.rmtree(decks_dir, ignore_errors=True)


def _dashboard_cache_fresh(cache_path: Path) -> bool:
    """Invalidate cached HTML when the dashboard generator module changes."""
    if not cache_path.exists():
        return False
    try:
        gen_mtime = Path(_ai_excel_dashboard_mod.__file__).stat().st_mtime
        return cache_path.stat().st_mtime >= gen_mtime
    except OSError:
        return False


# ── Views ─────────────────────────────────────────────────────────────


@login_required
def index(request):
    """Show the clean upload form (Django template)."""
    if not _has_upload_perm(request.user):
        if _has_view_perm(request.user):
            return redirect("dashboard_list")
        lang = request.session.get("ui_lang", "ar")
        messages.error(request, get_ui(lang)["alert_no_upload_perm"])
        return redirect("login")

    template_types = DashboardTemplateType.objects.filter(is_active=True)
    return render(request, "reports_app/upload.html", {
        "icon_choices": ICON_CHOICES,
        "template_types": template_types,
    })


@login_required
@csrf_exempt
def analyze(request):
    """
    POST-only: read the uploaded Excel, store data in DB, redirect to dashboard list.
    No HTML generation at upload time — dashboards are generated on first view.
    """
    if not _has_upload_perm(request.user):
        lang = request.session.get("ui_lang", "ar")
        messages.error(request, get_ui(lang)["alert_no_upload_perm"])
        return redirect("index")

    if request.method == "GET":
        return redirect("index")
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    lang = request.session.get("ui_lang", "ar")
    ui = get_ui(lang)

    # Validate required fields
    dashboard_name = request.POST.get("dashboard_name", "").strip()
    icon = request.POST.get("icon", "").strip()
    description = request.POST.get("description", "").strip()
    template_type = request.POST.get("template_type", "ai").strip()

    if not dashboard_name:
        messages.error(request, ui["upload_err_name"])
        return redirect("index")

    if not icon:
        messages.error(request, ui["upload_err_icon"])
        return redirect("index")

    try:
        dashboard = store_upload_to_db(
            request,
            dashboard_name=dashboard_name,
            icon=icon,
            template_type=template_type,
            description=description,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("index")
    except Exception as exc:
        err = f"{'خطأ في معالجة الملف' if lang == 'ar' else 'File processing error'}: {exc}"
        messages.error(request, err)
        return redirect("index")

    messages.success(request, ui["upload_success"])
    return redirect("dashboard_list")


def _dashboard_reviews_url(request, dashboard: Dashboard) -> str:
    return request.build_absolute_uri(f"/api/dashboards/{dashboard.pk}/reviews/")


def _inject_served_dashboard_html(
    request, dashboard: Dashboard, html_content: str
) -> str:
    mail_url = request.build_absolute_uri("/api/send-obs-email")
    plan_url = request.build_absolute_uri("/api/parse-audit-plan-pptx")
    reviews_url = _dashboard_reviews_url(request, dashboard)
    html_content = inject_web_mail_api(html_content, mail_url, plan_url)
    return inject_dashboard_reviews_api(html_content, reviews_url)


def _review_author_display(user) -> str:
    full = (user.get_full_name() or "").strip()
    return full or user.username


def _serialize_dashboard_review(review: DashboardReview) -> dict:
    return {
        "id": review.pk,
        "body": review.body,
        "author": review.author.username,
        "author_display": _review_author_display(review.author),
        "created_at": review.created_at.strftime("%Y-%m-%d %H:%M"),
    }


@login_required
@csrf_exempt
@require_http_methods(["GET", "POST", "OPTIONS"])
def dashboard_reviews_api(request, pk: int):
    if request.method == "OPTIONS":
        return JsonResponse({}, status=204)
    if not _has_view_perm(request.user):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    dashboard = get_object_or_404(Dashboard, pk=pk)

    if request.method == "GET":
        reviews = dashboard.reviews.select_related("author").all()
        return JsonResponse(
            {
                "ok": True,
                "reviews": [_serialize_dashboard_review(r) for r in reviews],
            }
        )

    try:
        data = __import__("json").loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "bad_json"}, status=400)

    body = str(data.get("body", "")).strip()
    if not body:
        return JsonResponse({"ok": False, "error": "empty_body"}, status=400)
    if len(body) > 8000:
        return JsonResponse({"ok": False, "error": "body_too_long"}, status=400)

    review = DashboardReview.objects.create(
        dashboard=dashboard,
        author=request.user,
        body=body,
    )
    return JsonResponse(
        {"ok": True, "review": _serialize_dashboard_review(review)},
        status=201,
    )


@login_required
def dashboard_list(request):
    if not _has_view_perm(request.user):
        lang = request.session.get("ui_lang", "ar")
        messages.error(request, get_ui(lang)["alert_no_view_perm"])
        return redirect("index")

    dashboards = Dashboard.objects.select_related("created_by", "upload_session").all()
    return render(request, "reports_app/dashboard_list.html", {"dashboards": dashboards})


@login_required
def dashboard_detail(request, pk: int):
    if not _has_view_perm(request.user):
        lang = request.session.get("ui_lang", "ar")
        messages.error(request, get_ui(lang)["alert_no_view_perm"])
        return redirect("index")

    dashboard = get_object_or_404(Dashboard, pk=pk)
    return render(request, "reports_app/dashboard_detail.html", {"dashboard": dashboard})


@login_required
@require_http_methods(["POST"])
def dashboard_delete(request, pk: int):
    lang = request.session.get("ui_lang", "ar")
    ui = get_ui(lang)

    if not _has_delete_perm(request.user):
        messages.error(request, ui["alert_no_delete_perm"])
        return redirect("dashboard_list")

    dashboard = get_object_or_404(Dashboard, pk=pk)
    name = dashboard.name
    _cleanup_dashboard_files(dashboard)
    dashboard.delete()
    messages.success(request, ui["dl_delete_success"] + f" ({name})")
    return redirect("dashboard_list")


@login_required
def dashboard_serve(request, pk: int):
    """
    Serve the dashboard HTML.

    Cache is keyed by locale so Arabic and English versions are stored
    separately.  Cache is always bypassed with ?nocache=1.

    Priority:
      1. Per-locale cache file on disk → serve it.
      2. raw_data_json in UploadSession → generate, cache, serve.
      3. Legacy html_file (old architecture) → serve it.
      4. Nothing → 404.
    """
    if not _has_view_perm(request.user):
        return HttpResponse("403 Forbidden", status=403)

    dashboard = get_object_or_404(Dashboard, pk=pk)
    lang = report_locale_for_dashboard(dashboard, request)
    force_regen = request.GET.get("nocache") == "1"

    dashboards_dir = Path(settings.MEDIA_ROOT) / "dashboards"
    dashboards_dir.mkdir(parents=True, exist_ok=True)

    # Per-locale cache path: dashboards/{pk}_{locale}.html
    cache_filename = f"{dashboard.pk}_{lang}.html"
    cache_path = dashboards_dir / cache_filename

    # 1. Serve from per-locale cache (skip if generator was updated)
    if not force_regen and _dashboard_cache_fresh(cache_path):
        content = _inject_served_dashboard_html(request, dashboard, cache_path.read_text(encoding="utf-8"))
        resp = HttpResponse(content, content_type="text/html; charset=utf-8")
        resp["X-Frame-Options"] = "SAMEORIGIN"
        return resp

    # 2. Generate from DB if data is available
    session = dashboard.upload_session
    if session and session.raw_data_json:
        try:
            html_out = generate_from_db_data(dashboard, request, locale=lang)
        except Exception as exc:
            return HttpResponse(f"Error generating dashboard: {exc}", status=500)

        cache_path.write_text(html_out, encoding="utf-8")
        # Also keep the dashboard.html_file pointing to the default locale cache
        if not dashboard.html_file:
            dashboard.html_file = f"dashboards/{cache_filename}"
            dashboard.save(update_fields=["html_file"])

        resp = HttpResponse(html_out, content_type="text/html; charset=utf-8")
        resp["X-Frame-Options"] = "SAMEORIGIN"
        return resp

    # 3. Legacy: serve from the stored html_file path
    if dashboard.html_file:
        html_path = Path(settings.MEDIA_ROOT) / dashboard.html_file
        if html_path.exists():
            content = _inject_served_dashboard_html(
                request, dashboard, html_path.read_text(encoding="utf-8")
            )
            resp = HttpResponse(content, content_type="text/html; charset=utf-8")
            resp["X-Frame-Options"] = "SAMEORIGIN"
            return resp

    # 4. Nothing to serve
    ui = get_ui(lang)
    return HttpResponse(ui.get("dd_no_data", "No data stored."), status=404)


@require_GET
def api_version(request):
    module_file = str(getattr(_ai_excel_dashboard_mod, "__file__", ""))
    return JsonResponse(version_payload(module_file))


@require_GET
def favicon(request):
    icon_path = settings.BASE_DIR / "assets" / "app_icon.ico"
    if icon_path.exists():
        return FileResponse(open(icon_path, "rb"), content_type="image/x-icon")
    return HttpResponse(status=204)
