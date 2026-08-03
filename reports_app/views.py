"""Upload form, dashboard CRUD, serve HTML, and version API."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
import shutil

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

import ai_excel_dashboard as _ai_excel_dashboard_mod

# web_strings.py lives at the project root
_BASE_DIR = str(Path(__file__).resolve().parents[1])
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)
from web_strings import get_ui  # noqa: E402
from dashboard_locale import normalize_locale  # noqa: E402

from audit_app.company_access import (
    get_enabled_attachment_kinds,
    user_must_select_company,
)
from audit_app.models import (
    Dashboard,
    DashboardTemplateType,
    DashboardStatus,
    ICON_CHOICES,
    TEMPLATE_TYPE_CHOICES,
)
from .dashboard_workflow import (
    FILTER_ALL,
    activate_company_for_dashboard,
    approve_dashboard,
    available_dashboard_filters,
    can_user_delete_dashboard,
    can_user_manage_dashboard_viewers,
    can_user_manage_review_attachments,
    can_user_resubmit,
    can_user_return_published_to_review,
    can_user_review,
    can_user_save_dashboard_user_edits,
    can_user_submit,
    company_members_for_viewer_assignment,
    dashboards_queryset_for_user,
    filter_dashboards_queryset,
    get_dashboard_for_review,
    get_dashboard_for_user,
    get_dashboard_viewer_attachment_map,
    get_dashboard_viewer_user_ids,
    has_delete_perm,
    has_review_perm,
    has_upload_perm,
    has_dashboard_list_perm,
    load_dashboard_cross_company,
    reject_dashboard,
    return_published_dashboard_to_review,
    set_dashboard_viewers,
    soft_delete_dashboard,
    submit_dashboard,
    user_allowed_attachment_kinds,
)
from reports_app.workflow_engine import company_uses_workflow_v2
from .services.report_generation import (
    ATTACHMENT_SPECS,
    build_attachment_form_slots,
    version_payload,
    generate_from_db_data,
    inject_dashboard_serve_context,
    report_locale_for_dashboard,
    store_upload_to_db,
    update_dashboard_review_attachments,
    validate_dashboard_user_edits_payload,
    _existing_excel_names,
)

logger = logging.getLogger(__name__)


# ── Permission helpers ────────────────────────────────────────────────


def _active_company(request):
    return getattr(request, "active_company", None)


def _resolve_dashboard_request(request, pk: int, *, allow_deleted: bool = False):
    """Load a dashboard and align active company with its tenant."""
    dashboard = load_dashboard_cross_company(
        request.user,
        pk,
        allow_deleted=allow_deleted,
    )
    if not dashboard:
        return None
    if not activate_company_for_dashboard(request, dashboard):
        return None
    return dashboard


def _has_upload_perm(user, request) -> bool:
    return has_upload_perm(user, _active_company(request))


def _has_view_perm(user, request) -> bool:
    return has_dashboard_list_perm(user, _active_company(request))


def _has_delete_perm(user) -> bool:
    return has_delete_perm(user)


def _wants_json(request) -> bool:
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept


def render_page_not_found(request):
    """Styled 404 page (works in DEBUG mode; avoids Django technical 404)."""
    return render(request, "404.html", status=404)


def render_embed_not_found(request):
    """Minimal 404 for dashboard iframe embed."""
    return render(request, "reports_app/embed_not_found.html", status=404)


def page_not_found_view(request, exception=None):
    return render_page_not_found(request)


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
    """Invalidate cached HTML when dashboard generator or embedded assets change."""
    if not cache_path.exists():
        return False
    try:
        gen_mtime = Path(_ai_excel_dashboard_mod.__file__).stat().st_mtime
        ar_pkg = Path(__file__).resolve().parents[1] / "arabic_compliance_dashboard"
        ar_gen = ar_pkg / "generator.py"
        if ar_gen.is_file():
            gen_mtime = max(gen_mtime, ar_gen.stat().st_mtime)
        for asset_name in ("assets/dashboard.js", "assets/styles.css", "assets/body.html"):
            asset_path = ar_pkg / asset_name
            if asset_path.is_file():
                gen_mtime = max(gen_mtime, asset_path.stat().st_mtime)
        return cache_path.stat().st_mtime >= gen_mtime
    except OSError:
        return False


# ── Upload form helpers ───────────────────────────────────────────────


def _active_upload_template_codes() -> set[str]:
    codes = set(
        DashboardTemplateType.objects.filter(
            is_active=True,
            is_deleted=False,
        ).values_list("code", flat=True)
    )
    if codes:
        return codes
    return {code for code, _ in TEMPLATE_TYPE_CHOICES}


def _upload_form_from_post(post) -> dict:
    return {
        "dashboard_name": post.get("dashboard_name", "").strip(),
        "icon": post.get("icon", "").strip(),
        "description": post.get("description", "").strip(),
        "template_type": post.get("template_type", "").strip(),
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
        candidate = get_dashboard_for_user(
            request.user,
            int(str(resubmit_id).strip()),
            company=_active_company(request),
        )
        if candidate and can_user_resubmit(request.user, candidate, _active_company(request)):
            resubmit_dashboard = candidate
    selected_icon = (
        form.get("icon")
        or (resubmit_dashboard.icon if resubmit_dashboard else "")
        or "bi-bar-chart-line-fill"
    )
    selected_template = (
        form.get("template_type")
        or (resubmit_dashboard.template_type if resubmit_dashboard else "")
    )
    active_templates = list(
        DashboardTemplateType.objects.filter(
            is_active=True,
            is_deleted=False,
        )
    )
    if not selected_template and len(active_templates) == 1:
        selected_template = active_templates[0].code
    dashboard_name_value = (
        form.get("dashboard_name")
        or (resubmit_dashboard.name if resubmit_dashboard else "")
        or ""
    )
    lang = normalize_locale(request.session.get("ui_lang", "en"))
    existing_excel_names: list[str] = []
    has_existing_excel = False
    if resubmit_dashboard:
        existing_excel_names = _existing_excel_names(resubmit_dashboard)
        session = resubmit_dashboard.upload_session
        has_existing_excel = bool(
            existing_excel_names
            and session
            and session.raw_data_json
        )
    return {
        "icon_choices": ICON_CHOICES,
        "template_types": active_templates,
        "resubmit_dashboard": resubmit_dashboard,
        "is_edit_mode": resubmit_dashboard is not None,
        "existing_excel_names": existing_excel_names,
        "has_existing_excel": has_existing_excel,
        "attachment_slots": build_attachment_form_slots(
            resubmit_dashboard,
            locale=lang,
            company=_active_company(request),
        ),
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
    if user_must_select_company(request.user) and not _active_company(request):
        return redirect("select_company")

    if not _has_upload_perm(request.user, request):
        if _has_view_perm(request.user, request):
            return redirect("dashboard_list")
        lang = request.session.get("ui_lang", "en")
        messages.error(request, get_ui(lang)["alert_no_upload_perm"])
        return redirect("profile")

    return _render_upload_page(request)


@login_required
@csrf_exempt
def analyze(request):
    """
    POST-only: read the uploaded Excel, store data in DB, redirect to dashboard list.
    No HTML generation at upload time — dashboards are generated on first view.
    """
    if user_must_select_company(request.user) and not _active_company(request):
        return redirect("select_company")

    if not _has_upload_perm(request.user, request):
        lang = request.session.get("ui_lang", "en")
        messages.error(request, get_ui(lang)["alert_no_upload_perm"])
        return redirect("upload")

    if request.method == "GET":
        return redirect("upload")
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    lang = request.session.get("ui_lang", "en")
    ui = get_ui(lang)

    form = _upload_form_from_post(request.POST)
    dashboard_name = form["dashboard_name"]
    icon = form["icon"]
    description = form["description"]
    template_type = form["template_type"]

    valid_template_codes = _active_upload_template_codes()
    if not template_type and len(valid_template_codes) == 1:
        template_type = next(iter(valid_template_codes))

    if not dashboard_name:
        messages.error(request, ui["upload_err_name"])
        return _render_upload_page(request, form)

    if not icon:
        messages.error(request, ui["upload_err_icon"])
        return _render_upload_page(request, form)

    valid_template_codes = _active_upload_template_codes()
    if template_type not in valid_template_codes:
        messages.error(request, ui["upload_err_template"])
        return _render_upload_page(request, form)

    resubmit_dashboard = None
    resubmit_raw = form["resubmit_dashboard_id"]
    was_draft_edit = False
    if resubmit_raw.isdigit():
        candidate = get_dashboard_for_user(
            request.user, int(resubmit_raw), company=_active_company(request)
        )
        if candidate and can_user_resubmit(request.user, candidate, _active_company(request)):
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

    _clear_dashboard_html_cache(dashboard)

    if resubmit_dashboard:
        dashboard.save(update_fields=["html_file"])
        if was_draft_edit:
            messages.success(request, ui.get("wf_edit_draft_success", ui["upload_success"]))
        else:
            messages.success(request, ui.get("wf_resubmit_success", ui["upload_success"]))
    else:
        messages.success(request, ui.get("upload_success_draft", ui["upload_success"]))

    company = _active_company(request)
    legacy_notify = company is None or not company_uses_workflow_v2(company)
    if legacy_notify:
        from accounts_app.services.workflow_email import notify_reviewers_pending

        submit_kind = "new"
        if resubmit_dashboard:
            submit_kind = "edit" if was_draft_edit else "resubmit"
        try:
            notify_reviewers_pending(
                dashboard,
                base_url=request.build_absolute_uri("/"),
                submit_kind=submit_kind,
            )
        except Exception:
            logger.exception(
                "Failed to send pending-review notification for dashboard %s",
                dashboard.pk,
            )

    return redirect("dashboard_list")


def _inject_served_dashboard_html(
    request, dashboard: Dashboard, html_content: str
) -> str:
    mail_url = request.build_absolute_uri("/api/send-obs-email")
    plan_url = request.build_absolute_uri("/api/parse-audit-plan-pptx")
    company = _active_company(request)
    can_save = can_user_save_dashboard_user_edits(request.user, dashboard, company)
    save_url = (
        request.build_absolute_uri(reverse("dashboard_user_edits", args=[dashboard.pk]))
        if can_save
        else ""
    )
    allowed_kinds = user_allowed_attachment_kinds(
        request.user, dashboard, company
    )
    return inject_dashboard_serve_context(
        html_content,
        mail_url=mail_url,
        plan_url=plan_url,
        user_edits_save_url=save_url,
        can_save_user_edits=can_save,
        user_edits_json=dashboard.user_edits_json or "",
        allowed_attachment_kinds=allowed_kinds,
    )


def _send_publish_notifications(request, dashboard, reviewer):
    from accounts_app.services.workflow_email import (
        notify_creator_published,
        notify_viewers_published,
    )

    base_url = request.build_absolute_uri("/")
    try:
        notify_viewers_published(dashboard, base_url=base_url, reviewer=reviewer)
    except Exception:
        logger.exception("Failed to send publish notification for dashboard %s", dashboard.pk)
    try:
        notify_creator_published(dashboard, base_url=base_url, reviewer=reviewer)
    except Exception:
        logger.exception("Failed to send creator publish notification for dashboard %s", dashboard.pk)


@login_required
def dashboard_list(request):
    if user_must_select_company(request.user) and not _active_company(request):
        return redirect("select_company")

    if not _has_view_perm(request.user, request):
        lang = request.session.get("ui_lang", "en")
        messages.error(request, get_ui(lang)["alert_no_view_perm"])
        return redirect("profile")

    show_trash = False
    dashboards = dashboards_queryset_for_user(
        request.user, _active_company(request)
    )
    company = _active_company(request)
    filter_key = request.GET.get("filter", "").strip()
    if not filter_key and request.session.get("dashboard_list_filter"):
        filter_key = request.session.get("dashboard_list_filter", FILTER_ALL)
    available_filters = available_dashboard_filters(request.user, company, dashboards)
    lang = request.session.get("ui_lang", "en")
    ui = get_ui(lang)
    if available_filters:
        for item in available_filters:
            item["label"] = ui.get(item["label_key"], item["label_key"])
    if available_filters:
        valid_keys = {item["key"] for item in available_filters}
        if filter_key not in valid_keys:
            filter_key = FILTER_ALL
        request.session["dashboard_list_filter"] = filter_key
        if filter_key != FILTER_ALL:
            dashboards = filter_dashboards_queryset(
                dashboards, request.user, company, filter_key
            )
    else:
        filter_key = FILTER_ALL
    deletable_dashboard_ids = {
        dashboard.pk
        for dashboard in dashboards
        if can_user_delete_dashboard(request.user, dashboard, company)
    }
    manageable_viewer_dashboard_ids = {
        dashboard.pk
        for dashboard in dashboards
        if can_user_manage_dashboard_viewers(request.user, dashboard, company)
    }
    returnable_dashboard_ids = {
        dashboard.pk
        for dashboard in dashboards
        if can_user_return_published_to_review(request.user, dashboard, company)
    }
    undo_deleted_pk = None
    undo_deleted_name = ""
    return render(
        request,
        "reports_app/dashboard_list.html",
        {
            "dashboards": dashboards,
            "deletable_dashboard_ids": deletable_dashboard_ids,
            "manageable_viewer_dashboard_ids": manageable_viewer_dashboard_ids,
            "returnable_dashboard_ids": returnable_dashboard_ids,
            "can_review_dashboards": has_review_perm(
                request.user, company
            ),
            "dashboard_filters": available_filters,
            "active_dashboard_filter": filter_key,
            "show_trash": show_trash,
            "undo_deleted_pk": undo_deleted_pk,
            "undo_deleted_name": undo_deleted_name,
        },
    )


@login_required
def dashboard_detail(request, pk: int):
    if not _has_view_perm(request.user, request):
        lang = request.session.get("ui_lang", "en")
        messages.error(request, get_ui(lang)["alert_no_view_perm"])
        return redirect("profile")

    dashboard = _resolve_dashboard_request(request, pk)
    if not dashboard:
        return render_page_not_found(request)
    rejection_logs = dashboard.rejection_logs.select_related("rejected_by").all()
    company = _active_company(request)
    can_manage_review_attachments = can_user_manage_review_attachments(
        request.user, dashboard, company
    )
    return render(
        request,
        "reports_app/dashboard_detail.html",
        {
            "dashboard": dashboard,
            "rejection_logs": rejection_logs,
            "can_review_dashboards": has_review_perm(request.user, company),
            "can_resubmit": can_user_resubmit(request.user, dashboard, company),
            "can_submit_for_review": can_user_submit(request.user, dashboard, company),
            "can_approve_reject": can_user_review(request.user, dashboard, company),
            "can_return_to_review": can_user_return_published_to_review(
                request.user, dashboard, company
            ),
            "can_manage_review_attachments": can_manage_review_attachments,
            "review_attachment_slots": (
                build_attachment_form_slots(dashboard, locale=request.session.get("ui_lang", "en"), company=company)
                if can_manage_review_attachments
                else []
            ),
            "can_manage_dashboard_viewers": can_user_manage_dashboard_viewers(
                request.user, dashboard, company
            ),
            "can_delete_dashboard": can_user_delete_dashboard(
                request.user, dashboard, company
            ),
        },
    )


@login_required
@require_http_methods(["POST"])
def dashboard_delete(request, pk: int):
    lang = request.session.get("ui_lang", "en")
    ui = get_ui(lang)

    dashboard = _resolve_dashboard_request(request, pk)
    if not dashboard or dashboard.is_deleted:
        if _wants_json(request):
            return JsonResponse({"error": "not_found"}, status=404)
        return render_page_not_found(request)

    company = _active_company(request)
    if not can_user_delete_dashboard(request.user, dashboard, company):
        messages.error(request, ui["alert_no_delete_perm"])
        return redirect("dashboard_list")

    name = dashboard.name
    soft_delete_dashboard(dashboard, request.user)

    if _wants_json(request):
        return JsonResponse({"ok": True, "pk": pk, "name": name})

    messages.success(request, ui["dl_delete_success"] + f" ({name})")
    return redirect("dashboard_list")


@login_required
@require_http_methods(["POST"])
def dashboard_restore(request, pk: int):
    return render_page_not_found(request)


@login_required
@require_http_methods(["POST"])
def dashboard_user_edits(request, pk: int):
    """Persist audit-plan table edits and review notes for a dashboard."""
    import json

    dashboard = _resolve_dashboard_request(request, pk)
    if not dashboard:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)

    company = _active_company(request)
    if not can_user_save_dashboard_user_edits(request.user, dashboard, company):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    try:
        raw = request.body.decode("utf-8") if request.body else ""
        data = json.loads(raw or "{}")
        payload = validate_dashboard_user_edits_payload(data)
    except (json.JSONDecodeError, ValueError, TypeError):
        return JsonResponse({"ok": False, "error": "invalid_payload"}, status=400)

    dashboard.user_edits_json = json.dumps(payload, ensure_ascii=False)
    dashboard.save(update_fields=["user_edits_json"])
    return JsonResponse({"ok": True})


@login_required
@require_http_methods(["POST"])
def dashboard_review_attachments(request, pk: int):
    """Allow reviewer to add/replace/remove deck attachments before publish."""
    lang = request.session.get("ui_lang", "en")
    ui = get_ui(lang)

    dashboard = _resolve_dashboard_request(request, pk)
    if not dashboard:
        messages.error(request, ui.get("wf_dashboard_not_found", "Dashboard not found."))
        return redirect("dashboard_list")

    company = _active_company(request)
    if not can_user_manage_review_attachments(request.user, dashboard, company):
        messages.error(request, ui.get("wf_review_attach_forbidden", "Cannot edit attachments."))
        return redirect("dashboard_detail", pk=pk)

    try:
        update_dashboard_review_attachments(request, dashboard, company=company)
        _clear_dashboard_html_cache(dashboard)
        dashboard.save(update_fields=["html_file"])
        messages.success(request, ui.get("wf_review_attach_saved", "Attachments updated."))
        return redirect(f"{reverse('dashboard_detail', args=[pk])}?attachments_updated=1")
    except ValueError as exc:
        if str(exc) == "not_under_review":
            messages.error(request, ui.get("wf_review_not_pending", "This dashboard is not pending review."))
        else:
            messages.error(request, str(exc))
    except Exception:
        logger.exception("Failed to update review attachments for dashboard %s", dashboard.pk)
        messages.error(request, ui.get("wf_review_attach_error", "Could not update attachments."))

    return redirect("dashboard_detail", pk=pk)


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
    if not _has_view_perm(request.user, request):
        return HttpResponse("403 Forbidden", status=403)

    dashboard = _resolve_dashboard_request(request, pk)
    if not dashboard:
        return render_embed_not_found(request)
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

        content = _inject_served_dashboard_html(request, dashboard, html_out)
        resp = HttpResponse(content, content_type="text/html; charset=utf-8")
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
    if get_dashboard_for_user(
        request.user, dashboard.pk, company=_active_company(request)
    ):
        messages.warning(request, not_pending_msg)
        return redirect("dashboard_detail", pk=dashboard.pk)
    messages.warning(request, not_pending_msg)
    return redirect("dashboard_list")


@login_required
@require_http_methods(["POST"])
def dashboard_approve(request, pk: int):
    lang = request.session.get("ui_lang", "en")
    ui = get_ui(lang)
    dashboard = _resolve_dashboard_request(request, pk)
    if not dashboard:
        messages.error(request, ui.get("wf_dashboard_not_found", "Dashboard not found."))
        return redirect("dashboard_list")

    company = _active_company(request)
    if not has_review_perm(request.user, company):
        messages.error(request, ui.get("wf_review_forbidden", "No permission to review dashboards."))
        return redirect("dashboard_list")

    if not can_user_review(request.user, dashboard, company):
        if dashboard.status == DashboardStatus.PUBLISHED:
            msg = ui.get("wf_already_published", "This dashboard is already published.")
        elif dashboard.status == DashboardStatus.REJECTED:
            msg = ui.get("wf_already_rejected", "This dashboard was already rejected.")
        else:
            msg = ui.get("wf_review_not_pending", "This dashboard is not pending review.")
        return _review_action_redirect(request, dashboard, not_pending_msg=msg)

    approve_dashboard(dashboard, request.user)
    dashboard.refresh_from_db()
    messages.success(request, ui.get("wf_approve_success", "Dashboard published."))
    _send_publish_notifications(request, dashboard, request.user)

    return redirect("dashboard_list")


@login_required
@require_http_methods(["POST"])
def dashboard_reject(request, pk: int):
    lang = request.session.get("ui_lang", "en")
    ui = get_ui(lang)
    dashboard = _resolve_dashboard_request(request, pk)
    if not dashboard:
        messages.error(request, ui.get("wf_dashboard_not_found", "Dashboard not found."))
        return redirect("dashboard_list")

    company = _active_company(request)
    if not has_review_perm(request.user, company):
        messages.error(request, ui.get("wf_review_forbidden", "No permission to review dashboards."))
        return redirect("dashboard_list")

    if not can_user_review(request.user, dashboard, company):
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

    from accounts_app.services.workflow_email import notify_creator_rejected

    try:
        notify_creator_rejected(
            dashboard,
            base_url=request.build_absolute_uri("/"),
            reason=reason,
            reviewer=request.user,
        )
    except Exception:
        logger.exception("Failed to send rejection notification for dashboard %s", dashboard.pk)

    return redirect("dashboard_list")


@login_required
@require_http_methods(["POST"])
def dashboard_return_to_review(request, pk: int):
    lang = request.session.get("ui_lang", "en")
    ui = get_ui(lang)
    dashboard = _resolve_dashboard_request(request, pk)
    if not dashboard:
        messages.error(request, ui.get("wf_dashboard_not_found", "Dashboard not found."))
        return redirect("dashboard_list")

    company = _active_company(request)
    if not can_user_return_published_to_review(request.user, dashboard, company):
        messages.error(
            request,
            ui.get(
                "wf_return_to_review_forbidden",
                "You cannot return this dashboard to review.",
            ),
        )
        return redirect("dashboard_detail", pk=pk)

    return_published_dashboard_to_review(request.user, dashboard, company)
    _clear_dashboard_html_cache(dashboard)
    messages.success(
        request,
        ui.get(
            "wf_return_to_review_success",
            "Dashboard returned to pending review.",
        ),
    )

    from accounts_app.services.workflow_email import notify_reviewers_pending

    try:
        notify_reviewers_pending(
            dashboard,
            base_url=request.build_absolute_uri("/"),
            submit_kind="return_to_review",
        )
    except Exception:
        logger.exception(
            "Failed to send return-to-review notification for dashboard %s",
            dashboard.pk,
        )

    return redirect("dashboard_list")


@login_required
@require_http_methods(["POST"])
def dashboard_submit(request, pk: int):
    lang = request.session.get("ui_lang", "en")
    ui = get_ui(lang)
    dashboard = _resolve_dashboard_request(request, pk)
    if not dashboard:
        messages.error(request, ui.get("wf_dashboard_not_found", "Dashboard not found."))
        return redirect("dashboard_list")

    company = _active_company(request)
    if not can_user_submit(request.user, dashboard, company):
        messages.error(request, ui.get("wf_submit_forbidden", "Cannot submit this dashboard."))
        return redirect("dashboard_detail", pk=pk)

    try:
        submit_dashboard(request.user, dashboard, company)
    except PermissionError:
        messages.error(request, ui.get("wf_submit_forbidden", "Cannot submit this dashboard."))
        return redirect("dashboard_detail", pk=pk)

    messages.success(request, ui.get("wf_submit_success", "Dashboard submitted for review."))

    from accounts_app.services.workflow_email import notify_reviewers_pending

    try:
        notify_reviewers_pending(
            dashboard,
            base_url=request.build_absolute_uri("/"),
            submit_kind="new",
        )
    except Exception:
        logger.exception("Failed to send submit notification for dashboard %s", dashboard.pk)

    return redirect("dashboard_list")


def _load_dashboard_for_viewer_assignment(request, pk: int) -> Dashboard | None:
    """Load dashboard in active company for viewer-management API (no visibility gate)."""
    company = _active_company(request)
    try:
        dashboard = Dashboard.objects.select_related("company", "created_by").get(
            pk=pk,
            is_deleted=False,
        )
    except Dashboard.DoesNotExist:
        return None
    if company is not None and dashboard.company_id != company.id:
        return None
    if company is None and not request.user.is_superuser:
        return None
    return dashboard


def _viewer_assignment_members_context(dashboard: Dashboard, ui: dict) -> tuple[list[dict], list[dict]]:
    """Build member rows + enabled attachment kind options for viewer UI."""
    assigned_map = get_dashboard_viewer_attachment_map(dashboard)
    members: list[dict] = []
    if dashboard.company_id:
        for user in company_members_for_viewer_assignment(dashboard.company):
            full = user.get_full_name().strip()
            kinds = assigned_map.get(user.pk, [])
            members.append(
                {
                    "id": user.pk,
                    "username": user.username,
                    "name": full or user.username,
                    "assigned": user.pk in assigned_map,
                    "attachment_kinds": kinds,
                    "attachment_kinds_set": set(kinds),
                }
            )
    enabled = get_enabled_attachment_kinds(dashboard.company)
    kind_options: list[dict] = []
    for spec in ATTACHMENT_SPECS:
        if spec["kind"] not in enabled:
            continue
        label = ui.get(spec["ui_label"], spec["kind"])
        kind_options.append({"kind": spec["kind"], "label": label})
    return members, kind_options


def _parse_viewer_form_assignments(request) -> tuple[list[int], dict[int, list[str]]]:
    """Parse classic HTML form: assigned + kinds_<user_id>."""
    user_ids: list[int] = []
    for raw in request.POST.getlist("assigned"):
        try:
            user_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    kinds_by_user: dict[int, list[str]] = {}
    for uid in user_ids:
        kinds_by_user[uid] = [
            str(k) for k in request.POST.getlist(f"kinds_{uid}") if str(k).strip()
        ]
    return user_ids, kinds_by_user


def _apply_viewer_assignments(
    request,
    dashboard: Dashboard,
    user_ids: list[int],
    kinds_by_user: dict[int, list[str]] | None,
):
    added, removed = set_dashboard_viewers(
        dashboard,
        user_ids,
        granted_by=request.user,
        attachment_kinds_by_user=kinds_by_user,
    )
    if added:
        from accounts_app.services.workflow_email import notify_viewers_assigned

        try:
            notify_viewers_assigned(
                dashboard,
                user_ids=sorted(added),
                base_url=request.build_absolute_uri("/"),
                granted_by=request.user,
            )
        except Exception:
            logger.exception(
                "Failed to send viewer assignment email for dashboard %s",
                dashboard.pk,
            )
    return added, removed


@login_required
@require_http_methods(["GET", "POST"])
def dashboard_viewers_manage(request, pk: int):
    """
    Server-rendered viewer + attachment-kind assignment page.

    Avoids reliance on cached/hashed ``dashboard_viewers.js`` on VPS deploys.
    """
    lang = request.session.get("ui_lang", "en")
    ui = get_ui(lang)
    dashboard = _load_dashboard_for_viewer_assignment(request, pk)
    if not dashboard:
        messages.error(request, ui.get("wf_dashboard_not_found", "Dashboard not found."))
        return redirect("dashboard_list")

    company = _active_company(request) or dashboard.company
    if not can_user_manage_dashboard_viewers(request.user, dashboard, company):
        messages.error(request, ui.get("dv_forbidden", "No permission to manage viewers."))
        return redirect("dashboard_detail", pk=pk)

    if request.method == "POST":
        user_ids, kinds_by_user = _parse_viewer_form_assignments(request)
        _apply_viewer_assignments(
            request,
            dashboard,
            user_ids,
            kinds_by_user,
        )
        messages.success(request, ui.get("dv_saved", "Viewer assignments saved."))
        return redirect("dashboard_viewers_manage", pk=pk)

    members, kind_options = _viewer_assignment_members_context(dashboard, ui)
    return render(
        request,
        "reports_app/dashboard_viewers_manage.html",
        {
            "dashboard": dashboard,
            "members": members,
            "kind_options": kind_options,
            "ui": ui,
            "is_rtl": lang == "ar",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def dashboard_viewers(request, pk: int):
    lang = request.session.get("ui_lang", "en")
    ui = get_ui(lang)
    dashboard = _load_dashboard_for_viewer_assignment(request, pk)
    if not dashboard:
        if _wants_json(request):
            return JsonResponse({"error": "not_found"}, status=404)
        messages.error(request, ui.get("wf_dashboard_not_found", "Dashboard not found."))
        return redirect("dashboard_list")

    company = _active_company(request) or dashboard.company
    if not can_user_manage_dashboard_viewers(request.user, dashboard, company):
        if _wants_json(request):
            return JsonResponse({"error": "forbidden"}, status=403)
        messages.error(request, ui.get("dv_forbidden", "No permission to manage viewers."))
        return redirect("dashboard_detail", pk=pk)

    # Non-AJAX browser navigation → dedicated manage page (authoritative UI).
    if request.method == "GET" and not _wants_json(request):
        return redirect("dashboard_viewers_manage", pk=pk)

    if request.method == "GET":
        members, kind_options = _viewer_assignment_members_context(dashboard, ui)
        assigned_ids = sorted(m["id"] for m in members if m["assigned"])
        api_members = [
            {
                "id": m["id"],
                "username": m["username"],
                "name": m["name"],
                "assigned": m["assigned"],
                "attachment_kinds": m["attachment_kinds"],
            }
            for m in members
        ]
        return JsonResponse(
            {
                "members": api_members,
                "assigned_ids": assigned_ids,
                "attachment_kind_options": kind_options,
            }
        )

    raw_assignments = request.POST.get("assignments", "").strip()
    user_ids: list[int] = []
    kinds_by_user: dict[int, list[str]] = {}
    used_assignments_payload = False

    if raw_assignments:
        import json as _json

        try:
            parsed = _json.loads(raw_assignments)
        except (_json.JSONDecodeError, TypeError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            used_assignments_payload = True
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                try:
                    uid = int(item.get("user_id"))
                except (TypeError, ValueError):
                    continue
                user_ids.append(uid)
                kinds = item.get("attachment_kinds") or []
                if isinstance(kinds, list):
                    kinds_by_user[uid] = [str(k) for k in kinds]
                else:
                    kinds_by_user[uid] = []
    else:
        # Form fields from manage page or legacy user_ids-only posts.
        if "assigned" in request.POST:
            user_ids, kinds_by_user = _parse_viewer_form_assignments(request)
            used_assignments_payload = True
        else:
            raw_ids = request.POST.getlist("user_ids")
            for raw in raw_ids:
                try:
                    user_ids.append(int(raw))
                except (TypeError, ValueError):
                    continue

    added, removed = _apply_viewer_assignments(
        request,
        dashboard,
        user_ids,
        kinds_by_user if used_assignments_payload else None,
    )

    if _wants_json(request):
        return JsonResponse(
            {
                "ok": True,
                "assigned_ids": sorted(get_dashboard_viewer_user_ids(dashboard)),
                "added": sorted(added),
                "removed": sorted(removed),
            }
        )

    messages.success(request, ui.get("dv_saved", "Viewer assignments saved."))
    return redirect("dashboard_viewers_manage", pk=pk)


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
