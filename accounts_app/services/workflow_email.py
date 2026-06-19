"""Dashboard workflow notification emails (bilingual)."""
from __future__ import annotations

import logging
from html import escape
from typing import Iterable

from django.contrib.auth.models import User

from accounts_app.services.email_branding import (
    bilingual_footer_plain,
    build_branded_email_html,
    render_bilingual_block,
    render_bilingual_plain,
    render_cta_button,
    resolve_logo_url,
    send_branded_email_smtp,
)
from accounts_app.services.email_dispatch import dispatch_in_background
from audit_app.models import Company, CompanyMembership, Dashboard

logger = logging.getLogger(__name__)

SUBMIT_KIND_LABELS = {
    "new": ("طلب جديد", "New submission"),
    "edit": ("تعديل مسودة", "Draft edit"),
    "resubmit": ("إعادة إرسال", "Resubmission"),
}


def build_auth_link(base_url: str, target_path: str) -> str:
    """Absolute URL to the workflow target page (auth redirect handled by the app)."""
    safe_path = target_path if target_path.startswith("/") else f"/{target_path}"
    return f"{base_url.rstrip('/')}{safe_path}"


def _user_display(user: User | None) -> str:
    if user is None:
        return "—"
    full = user.get_full_name().strip()
    return full or user.username


def _eligible_email(user: User | None) -> str | None:
    if user is None or not user.is_active:
        return None
    email = (user.email or "").strip()
    if not email:
        return None
    profile = getattr(user, "profile", None)
    if profile and profile.is_deleted:
        return None
    return email


def _collect_emails(users: Iterable[User]) -> list[str]:
    emails: list[str] = []
    seen: set[str] = set()
    for user in users:
        email = _eligible_email(user)
        if email and email.lower() not in seen:
            seen.add(email.lower())
            emails.append(email)
    return emails


def _superuser_workflow_users(*, exclude_user_id: int | None = None) -> list[User]:
    qs = User.objects.filter(
        is_active=True,
        is_superuser=True,
        profile__receive_workflow_emails=True,
    ).select_related("profile")
    if exclude_user_id:
        qs = qs.exclude(pk=exclude_user_id)
    return list(qs)


def _reviewer_users(company: Company, *, exclude_user_id: int | None = None) -> list[User]:
    users: list[User] = []
    seen_ids: set[int] = set()

    membership_qs = CompanyMembership.objects.filter(
        company=company,
        can_review=True,
    ).select_related("user")
    if exclude_user_id:
        membership_qs = membership_qs.exclude(user_id=exclude_user_id)
    for membership in membership_qs:
        if membership.user_id not in seen_ids:
            seen_ids.add(membership.user_id)
            users.append(membership.user)

    for user in _superuser_workflow_users(exclude_user_id=exclude_user_id):
        if user.pk not in seen_ids:
            seen_ids.add(user.pk)
            users.append(user)

    return users


def _viewer_users(
    company: Company,
    *,
    exclude_user_id: int | None = None,
) -> list[User]:
    users: list[User] = []
    seen_ids: set[int] = set()

    membership_qs = CompanyMembership.objects.filter(
        company=company,
        can_view=True,
    ).select_related("user")
    if exclude_user_id:
        membership_qs = membership_qs.exclude(user_id=exclude_user_id)
    for membership in membership_qs:
        if membership.user_id not in seen_ids:
            seen_ids.add(membership.user_id)
            users.append(membership.user)

    for user in _superuser_workflow_users(exclude_user_id=exclude_user_id):
        if user.pk not in seen_ids:
            seen_ids.add(user.pk)
            users.append(user)

    return users


def _send_many(cfg, *, recipients: Iterable[str], subject: str, plain: str, html: str) -> None:
    for to_addr in recipients:
        try:
            send_branded_email_smtp(cfg, to_addr=to_addr, subject=subject, plain=plain, html=html)
        except Exception:
            logger.exception("Failed to send workflow email to %s", to_addr)


def _load_smtp_cfg():
    from ai_excel_dashboard import load_smtp_config

    cfg = load_smtp_config()
    if not cfg:
        raise ValueError("smtp_not_configured")
    return cfg


def _refresh_dashboard(dashboard_id: int) -> Dashboard:
    return Dashboard.objects.select_related("created_by", "company").get(pk=dashboard_id)


def notify_reviewers_pending(
    dashboard: Dashboard,
    *,
    base_url: str,
    submit_kind: str = "new",
) -> None:
    dispatch_in_background(
        _send_reviewers_pending,
        dashboard.pk,
        base_url,
        submit_kind,
    )


def _send_reviewers_pending(dashboard_id: int, base_url: str, submit_kind: str) -> None:
    dashboard = _refresh_dashboard(dashboard_id)
    company = dashboard.company
    if company is None:
        logger.warning("Skipping pending-review email: dashboard %s has no company", dashboard.pk)
        return
    try:
        cfg = _load_smtp_cfg()
    except ValueError:
        logger.warning("SMTP not configured; skipping pending-review notifications")
        return

    recipients = _collect_emails(
        _reviewer_users(company, exclude_user_id=dashboard.created_by_id)
    )
    if not recipients:
        logger.warning(
            "No reviewer recipients for dashboard %s (company=%s); check can_review users",
            dashboard.pk,
            company.code,
        )
        return

    kind_ar, kind_en = SUBMIT_KIND_LABELS.get(submit_kind, SUBMIT_KIND_LABELS["new"])
    dash_name = escape(dashboard.name)
    company_name = escape(company.name)
    creator = escape(_user_display(dashboard.created_by))
    link = build_auth_link(base_url, f"/dashboards/{dashboard.pk}/")

    text_ar = (
        f"<p style='margin:0 0 10px;'>السلام عليكم،</p>"
        f"<p style='margin:0 0 12px;'>يوجد طلب لوحة تحكم بانتظار المراجعة ({kind_ar}):</p>"
        f"<ul style='margin:0 0 12px;padding-right:20px;'>"
        f"<li><strong>اللوحة:</strong> {dash_name}</li>"
        f"<li><strong>الشركة:</strong> {company_name}</li>"
        f"<li><strong>المنشئ:</strong> {creator}</li>"
        f"</ul>"
    )
    text_en = (
        f"<p style='margin:0 0 10px;'>Hello,</p>"
        f"<p style='margin:0 0 12px;'>A dashboard is pending your review ({kind_en}):</p>"
        f"<ul style='margin:0 0 12px;padding-left:20px;'>"
        f"<li><strong>Dashboard:</strong> {dash_name}</li>"
        f"<li><strong>Company:</strong> {company_name}</li>"
        f"<li><strong>Submitted by:</strong> {creator}</li>"
        f"</ul>"
    )

    body_html = (
        render_bilingual_block(text_ar=text_ar, text_en=text_en)
        + render_cta_button(link, label_ar="مراجعة اللوحة", label_en="Review Dashboard")
    )

    plain = render_bilingual_plain(
        text_ar=(
            f"طلب مراجعة ({kind_ar})\n"
            f"اللوحة: {dashboard.name}\n"
            f"الشركة: {company.name}\n"
            f"المنشئ: {_user_display(dashboard.created_by)}\n"
            f"الرابط: {link}\n"
        ),
        text_en=(
            f"Pending review ({kind_en})\n"
            f"Dashboard: {dashboard.name}\n"
            f"Company: {company.name}\n"
            f"Submitted by: {_user_display(dashboard.created_by)}\n"
            f"Link: {link}\n"
        ),
    ) + "\n\n" + bilingual_footer_plain()

    subject = "طلب مراجعة لوحة Dashboard Pending Review"
    html = build_branded_email_html(
        header_ar="طلب مراجعة لوحة تحكم",
        header_en="Dashboard Pending Review",
        body_html=body_html,
        logo_url=resolve_logo_url(base_url=base_url, cfg=cfg),
    )
    _send_many(cfg, recipients=recipients, subject=subject, plain=plain, html=html)


def notify_creator_rejected(
    dashboard: Dashboard,
    *,
    base_url: str,
    reason: str,
    reviewer: User,
) -> None:
    dispatch_in_background(
        _send_creator_rejected,
        dashboard.pk,
        base_url,
        reason,
        reviewer.pk,
    )


def _send_creator_rejected(
    dashboard_id: int,
    base_url: str,
    reason: str,
    reviewer_id: int,
) -> None:
    dashboard = _refresh_dashboard(dashboard_id)
    try:
        reviewer = User.objects.get(pk=reviewer_id)
    except User.DoesNotExist:
        logger.warning("Skipping rejection email: reviewer %s not found", reviewer_id)
        return

    recipient = _eligible_email(dashboard.created_by)
    if not recipient:
        logger.warning(
            "Skipping rejection email: dashboard %s creator has no eligible email",
            dashboard.pk,
        )
        return
    try:
        cfg = _load_smtp_cfg()
    except ValueError:
        logger.warning("SMTP not configured; skipping rejection notification")
        return

    dash_name = escape(dashboard.name)
    reason_html = escape(reason.strip())
    reviewer_name = escape(_user_display(reviewer))
    link = build_auth_link(base_url, f"/dashboards/{dashboard.pk}/")

    text_ar = (
        f"<p style='margin:0 0 10px;'>السلام عليكم،</p>"
        f"<p style='margin:0 0 12px;'>تم رفض لوحة التحكم <strong>{dash_name}</strong>.</p>"
        f"<p style='margin:0 0 8px;'><strong>سبب الرفض:</strong> {reason_html}</p>"
        f"<p style='margin:0 0 8px;'><span dir='rtl'>بواسطة: {reviewer_name}</span></p>"
    )
    text_en = (
        f"<p style='margin:0 0 10px;'>Hello,</p>"
        f"<p style='margin:0 0 12px;'>Dashboard <strong>{dash_name}</strong> was rejected.</p>"
        f"<p style='margin:0 0 8px;'><strong>Rejection reason:</strong> {reason_html}</p>"
        f"<p style='margin:0 0 8px;'><span dir='ltr'>By: {reviewer_name}</span></p>"
    )

    body_html = (
        render_bilingual_block(text_ar=text_ar, text_en=text_en)
        + '<div style="margin-top:20px;">'
        + render_cta_button(link, label_ar="عرض اللوحة", label_en="View Dashboard")
        + "</div>"
    )

    plain = render_bilingual_plain(
        text_ar=(
            f"تم رفض لوحة: {dashboard.name}\n"
            f"سبب الرفض: {reason.strip()}\n"
            f"بواسطة: {_user_display(reviewer)}\n"
            f"الرابط: {link}\n"
        ),
        text_en=(
            f"Dashboard rejected: {dashboard.name}\n"
            f"Reason: {reason.strip()}\n"
            f"By: {_user_display(reviewer)}\n"
            f"Link: {link}\n"
        ),
    ) + "\n\n" + bilingual_footer_plain()

    subject = "رفض لوحة تحكم Dashboard Rejected"
    html = build_branded_email_html(
        header_ar="تم رفض لوحة التحكم",
        header_en="Dashboard Rejected",
        body_html=body_html,
        logo_url=resolve_logo_url(base_url=base_url, cfg=cfg),
    )
    try:
        send_branded_email_smtp(cfg, to_addr=recipient, subject=subject, plain=plain, html=html)
    except Exception:
        logger.exception("Failed to send rejection email to %s", recipient)


def notify_viewers_published(
    dashboard: Dashboard,
    *,
    base_url: str,
    reviewer: User,
) -> None:
    dispatch_in_background(
        _send_viewers_published,
        dashboard.pk,
        base_url,
        reviewer.pk,
    )


def _send_viewers_published(dashboard_id: int, base_url: str, reviewer_id: int) -> None:
    dashboard = _refresh_dashboard(dashboard_id)
    company = dashboard.company
    if company is None:
        logger.warning("Skipping publish email: dashboard %s has no company", dashboard.pk)
        return
    try:
        cfg = _load_smtp_cfg()
    except ValueError:
        logger.warning("SMTP not configured; skipping publish notifications")
        return

    recipients = _collect_emails(_viewer_users(company, exclude_user_id=reviewer_id))
    if not recipients:
        logger.warning(
            "No viewer recipients for dashboard %s (company=%s); check can_view users",
            dashboard.pk,
            company.code,
        )
        return

    try:
        reviewer = User.objects.get(pk=reviewer_id)
    except User.DoesNotExist:
        reviewer = None

    dash_name = escape(dashboard.name)
    company_name = escape(company.name)
    reviewer_name = escape(_user_display(reviewer))
    link = build_auth_link(base_url, "/")

    text_ar = (
        f"<p style='margin:0 0 10px;'>السلام عليكم،</p>"
        f"<p style='margin:0 0 12px;'>تم اعتماد لوحة تحكم جديدة</p>"
        f"<ul style='margin:0 0 12px;padding-right:20px;'>"
        f"<li><strong>اللوحة:</strong> {dash_name}</li>"
        f"<li><strong>الشركة:</strong> {company_name}</li>"
        f"<li><strong>اعتمدها:</strong> {reviewer_name}</li>"
        f"</ul>"
    )
    text_en = (
        f"<p style='margin:0 0 10px;'>Hello,</p>"
        f"<p style='margin:0 0 12px;'>A dashboard has been published</p>"
        f"<ul style='margin:0 0 12px;padding-left:20px;'>"
        f"<li><strong>Dashboard:</strong> {dash_name}</li>"
        f"<li><strong>Company:</strong> {company_name}</li>"
        f"<li><strong>Approved by:</strong> {reviewer_name}</li>"
        f"</ul>"
    )

    body_html = (
        render_bilingual_block(text_ar=text_ar, text_en=text_en)
        + render_cta_button(link, label_ar="عرض لوحات التحكم", label_en="View Dashboards")
    )

    plain = render_bilingual_plain(
        text_ar=(
            f"تم اعتماد لوحة: {dashboard.name}\n"
            f"الشركة: {company.name}\n"
            f"اعتمدها: {_user_display(reviewer)}\n"
            f"الرابط: {link}\n"
        ),
        text_en=(
            f"Dashboard published: {dashboard.name}\n"
            f"Company: {company.name}\n"
            f"Approved by: {_user_display(reviewer)}\n"
            f"Link: {link}\n"
        ),
    ) + "\n\n" + bilingual_footer_plain()

    subject = "اعتماد لوحة تحكم Dashboard Published"
    html = build_branded_email_html(
        header_ar="تم اعتماد لوحة تحكم",
        header_en="Dashboard Published",
        body_html=body_html,
        logo_url=resolve_logo_url(base_url=base_url, cfg=cfg),
    )
    _send_many(cfg, recipients=recipients, subject=subject, plain=plain, html=html)
