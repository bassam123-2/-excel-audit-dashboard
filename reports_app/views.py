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
from dashboard_locale import normalize_locale  # noqa: E402

from audit_app.models import Dashboard, DashboardTemplateType, ICON_CHOICES
from audit_app.models import DashboardStatus
from .dashboard_workflow import (
    approve_dashboard,
    can_user_resubmit,
    can_user_review,
    dashboards_queryset_for_user,
    deleted_dashboards_queryset_for_user,
    get_dashboard_for_review,
    get_dashboard_for_user,
    has_delete_perm,
    has_review_perm,
    reject_dashboard,
    restore_dashboard,
    soft_delete_dashboard,
)
from .services.report_generation import (
    build_attachment_form_slots,
    html_no_cache_response,
    version_payload,
    generate_from_db_data,
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
    return has_delete_perm(user)


def _clear_dashboard_html_cache(dashboard: Dashboard) -> None:
    """Remove generated HTML cache files only (keep deck attachments)."""
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
        dashboard.html_file = ""


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


# ── Upload form helpers ───────────────────────────────────────────────


def _upload_form_from_post(post) -> dict:
    return {
        "dashboard_name": post.get("dashboard_name", "").strip(),
        "icon": post.get("icon", "").strip(),
        "description": post.get("description", "").strip(),
        "template_type": post.get("template_type", "ai").strip() or "ai",
        "resubmit_dashboard_id": post.get("resubmit_dashboard_id", "").strip(),
    }


def _upload_page_context(request, form: dict | None = None) -> dict:
    if form is None:
        form = {}
    resubmit_dashboard = None
    resubmit_id = (
        form.get("resubmit_dashboard_id")
        or request.GET.get("resubmit", "")
    )
    if str(resubmit_id).strip().isdigit():
        candidate = get_dashboard_for_user(request.user, int(str(resubmit_id).strip()))
        if candidate and can_user_resubmit(request.user, candidate):
            resubmit_dashboard = candidate
    selected_icon = (
        form.get("icon")
        or (resubmit_dashboard.icon if resubmit_dashboard else "")
        or "bi-bar-chart-line-fill"
    )
    selected_template = (
        form.get("template_type")
        or (resubmit_dashboard.template_type if resubmit_dashboard else "")
        or "ai"
    )
    dashboard_name_value = (
        form.get("dashboard_name")
        or (resubmit_dashboard.name if resubmit_dashboard else "")
        or ""
    )
    lang = normalize_locale(request.session.get("ui_lang", "ar"))
    return {
        "icon_choices": ICON_CHOICES,
        "template_types": DashboardTemplateType.objects.filter(is_active=True),
        "resubmit_dashboard": resubmit_dashboard,
        "is_edit_mode": resubmit_dashboard is not None,
        "attachment_slots": build_attachment_form_slots(resubmit_dashboard, locale=lang),
        "form": form,
        "selected_icon": selected_icon,
        "selected_template": selected_template,
        "dashboard_name_value": dashboard_name_value,
    }


def _render_upload_page(request, form: dict | None = None):
    return render(request, "reports_app/upload.html", _upload_page_context(request, form))


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

    return _render_upload_page(request)


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

    form = _upload_form_from_post(request.POST)
    dashboard_name = form["dashboard_name"]
    icon = form["icon"]
    description = form["description"]
    template_type = form["template_type"]

    if not dashboard_name:
        messages.error(request, ui["upload_err_name"])
        return _render_upload_page(request, form)

    if not icon:
        messages.error(request, ui["upload_err_icon"])
        return _render_upload_page(request, form)

    resubmit_dashboard = None
    resubmit_raw = form["resubmit_dashboard_id"]
    was_draft_edit = False
    if resubmit_raw.isdigit():
        candidate = get_dashboard_for_user(request.user, int(resubmit_raw))
        if candidate and can_user_resubmit(request.user, candidate):
            resubmit_dashboard = candidate
            was_draft_edit = candidate.status == DashboardStatus.DRAFT
        else:
            messages.error(request, ui.get("wf_resubmit_forbidden", "Cannot resubmit this dashboard."))
            return redirect("dashboard_list")

    try:
        dashboard = store_upload_to_db(
            request,
            dashboard_name=dashboard_name,
            icon=icon,
            template_type=template_type,
            description=description,
            resubmit_dashboard=resubmit_dashboard,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return _render_upload_page(request, form)
    except Exception as exc:
        err = f"{'خطأ في معالجة الملف' if lang == 'ar' else 'File processing error'}: {exc}"
        messages.error(request, err)
        return _render_upload_page(request, form)

    if resubmit_dashboard:
        _clear_dashboard_html_cache(dashboard)
        dashboard.save(update_fields=["html_file"])
        if was_draft_edit:
            messages.success(request, ui.get("wf_edit_draft_success", ui["upload_success"]))
        else:
            messages.success(request, ui.get("wf_resubmit_success", ui["upload_success"]))
    else:
        messages.success(request, ui.get("upload_success_draft", ui["upload_success"]))
    return redirect("dashboard_list")


def _inject_served_dashboard_html(
    request, dashboard: Dashboard, html_content: str
) -> str:
    mail_url = request.build_absolute_uri("/api/send-obs-email")
    plan_url = request.build_absolute_uri("/api/parse-audit-plan-pptx")
    return inject_web_mail_api(html_content, mail_url, plan_url)


@login_required
def dashboard_list(request):
    if not _has_view_perm(request.user):
        lang = request.session.get("ui_lang", "ar")
        messages.error(request, get_ui(lang)["alert_no_view_perm"])
        return redirect("index")

    show_trash = request.GET.get("trash") == "1" and _has_delete_perm(request.user)
    if show_trash:
        dashboards = deleted_dashboards_queryset_for_user(request.user)
    else:
        dashboards = dashboards_queryset_for_user(request.user)
    return render(
        request,
        "reports_app/dashboard_list.html",
        {
            "dashboards": dashboards,
            "can_review_dashboards": has_review_perm(request.user),
            "show_trash": show_trash,
        },
    )


@login_required
def dashboard_detail(request, pk: int):
    if not _has_view_perm(request.user):
        lang = request.session.get("ui_lang", "ar")
        messages.error(request, get_ui(lang)["alert_no_view_perm"])
        return redirect("index")

    dashboard = get_dashboard_for_user(
        request.user, pk, allow_deleted=_has_delete_perm(request.user)
    )
    if not dashboard:
        raise Http404
    rejection_logs = dashboard.rejection_logs.select_related("rejected_by").all()
    return render(
        request,
        "reports_app/dashboard_detail.html",
        {
            "dashboard": dashboard,
            "rejection_logs": rejection_logs,
            "can_review_dashboards": has_review_perm(request.user),
            "can_resubmit": can_user_resubmit(request.user, dashboard),
            "can_approve_reject": can_user_review(request.user, dashboard),
            "is_deleted_view": dashboard.is_deleted,
        },
    )


@login_required
@require_http_methods(["POST"])
def dashboard_delete(request, pk: int):
    lang = request.session.get("ui_lang", "ar")
    ui = get_ui(lang)

    if not _has_delete_perm(request.user):
        messages.error(request, ui["alert_no_delete_perm"])
        return redirect("dashboard_list")

    dashboard = get_dashboard_for_user(request.user, pk)
    if not dashboard or dashboard.is_deleted:
        raise Http404
    name = dashboard.name
    soft_delete_dashboard(dashboard, request.user)
    messages.success(request, ui["dl_delete_success"] + f" ({name})")
    return redirect("dashboard_list")


@login_required
@require_http_methods(["POST"])
def dashboard_restore(request, pk: int):
    lang = request.session.get("ui_lang", "ar")
    ui = get_ui(lang)

    if not _has_delete_perm(request.user):
        messages.error(request, ui["alert_no_delete_perm"])
        return redirect("dashboard_list")

    dashboard = get_dashboard_for_user(request.user, pk, allow_deleted=True)
    if not dashboard or not dashboard.is_deleted:
        raise Http404
    name = dashboard.name
    restore_dashboard(dashboard)
    messages.success(request, ui["dl_restore_success"] + f" ({name})")
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

    dashboard = get_dashboard_for_user(
        request.user, pk, allow_deleted=_has_delete_perm(request.user)
    )
    if not dashboard:
        return HttpResponse("404 Not Found", status=404)
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


def _review_action_redirect(request, dashboard, *, not_pending_msg: str):
    """Redirect after a failed approve/reject with a clear message (never 404)."""
    if get_dashboard_for_user(request.user, dashboard.pk):
        messages.warning(request, not_pending_msg)
        return redirect("dashboard_detail", pk=dashboard.pk)
    messages.warning(request, not_pending_msg)
    return redirect("dashboard_list")


@login_required
@require_http_methods(["POST"])
def dashboard_approve(request, pk: int):
    lang = request.session.get("ui_lang", "ar")
    ui = get_ui(lang)
    if not has_review_perm(request.user):
        messages.error(request, ui.get("wf_review_forbidden", "No permission to review dashboards."))
        return redirect("dashboard_list")

    dashboard = get_dashboard_for_review(request.user, pk)
    if not dashboard:
        messages.error(request, ui.get("wf_dashboard_not_found", "Dashboard not found."))
        return redirect("dashboard_list")

    if not can_user_review(request.user, dashboard):
        if dashboard.status == DashboardStatus.PUBLISHED:
            msg = ui.get("wf_already_published", "This dashboard is already published.")
        elif dashboard.status == DashboardStatus.REJECTED:
            msg = ui.get("wf_already_rejected", "This dashboard was already rejected.")
        else:
            msg = ui.get("wf_review_not_pending", "This dashboard is not pending review.")
        return _review_action_redirect(request, dashboard, not_pending_msg=msg)

    approve_dashboard(dashboard, request.user)
    messages.success(request, ui.get("wf_approve_success", "Dashboard published."))
    return redirect("dashboard_list")


@login_required
@require_http_methods(["POST"])
def dashboard_reject(request, pk: int):
    lang = request.session.get("ui_lang", "ar")
    ui = get_ui(lang)
    if not has_review_perm(request.user):
        messages.error(request, ui.get("wf_review_forbidden", "No permission to review dashboards."))
        return redirect("dashboard_list")

    dashboard = get_dashboard_for_review(request.user, pk)
    if not dashboard:
        messages.error(request, ui.get("wf_dashboard_not_found", "Dashboard not found."))
        return redirect("dashboard_list")

    if not can_user_review(request.user, dashboard):
        if dashboard.status == DashboardStatus.REJECTED:
            msg = ui.get("wf_already_rejected", "This dashboard was already rejected.")
        elif dashboard.status == DashboardStatus.PUBLISHED:
            msg = ui.get("wf_already_published", "This dashboard is already published.")
        else:
            msg = ui.get("wf_review_not_pending", "This dashboard is not pending review.")
        return _review_action_redirect(request, dashboard, not_pending_msg=msg)

    reason = request.POST.get("rejection_reason", "").strip()
    if not reason:
        messages.error(request, ui.get("wf_reject_reason_required", "Rejection reason is required."))
        return redirect("dashboard_detail", pk=pk)

    reject_dashboard(dashboard, request.user, reason)
    _clear_dashboard_html_cache(dashboard)
    dashboard.save(update_fields=["html_file"])
    messages.success(request, ui.get("wf_reject_success", "Dashboard rejected."))
    return redirect("dashboard_list")


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
