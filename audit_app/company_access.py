from __future__ import annotations

from django.db.models import QuerySet

from audit_app.models import ATTACHMENT_KIND_CODES, Company, CompanyAttachmentSetting, CompanyMembership

SESSION_ACTIVE_COMPANY_KEY = "active_company_id"


def active_companies_exist() -> bool:
    return Company.objects.filter(is_active=True).exists()


def user_can_manage_companies(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.has_perm("audit_app.add_company") or user.has_perm("audit_app.change_company")


def user_companies(user) -> QuerySet[Company]:
    if not user.is_authenticated:
        return Company.objects.none()
    if user.is_superuser:
        return Company.objects.filter(is_active=True).order_by("code")
    return (
        Company.objects.filter(is_active=True, memberships__user=user)
        .distinct()
        .order_by("code")
    )


def user_membership(user, company: Company | None) -> CompanyMembership | None:
    if not user.is_authenticated or company is None:
        return None
    if user.is_superuser:
        return CompanyMembership(
            user=user,
            company=company,
            can_upload=True,
            can_view=True,
            can_view_own_only=False,
            can_review=True,
            can_delete_drafts=True,
        )
    try:
        return CompanyMembership.objects.get(user=user, company=company)
    except CompanyMembership.DoesNotExist:
        return None


def clear_active_company(request) -> None:
    request.session.pop(SESSION_ACTIVE_COMPANY_KEY, None)


def user_must_select_company(user) -> bool:
    return user_companies(user).count() > 1


def has_company_perm(user, company: Company | None, perm: str) -> bool:
    if not user.is_authenticated or not active_companies_exist():
        return False
    if user.is_superuser:
        return True
    if company is None:
        return False
    membership = user_membership(user, company)
    if membership is None:
        return False
    if perm == "upload":
        return membership.can_upload
    if perm == "view":
        return membership.can_view
    if perm == "view_own":
        return membership.can_view_own_only
    if perm == "review":
        return membership.can_review
    if perm == "delete_draft":
        return membership.can_delete_drafts
    return False


def set_active_company(request, company_id: int) -> bool:
    company = Company.objects.filter(pk=company_id, is_active=True).first()
    if company is None:
        return False
    if not request.user.is_superuser:
        if not CompanyMembership.objects.filter(user=request.user, company=company).exists():
            return False
    request.session[SESSION_ACTIVE_COMPANY_KEY] = company.pk
    return True


def get_active_company(request) -> Company | None:
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return None

    company_id = request.session.get(SESSION_ACTIVE_COMPANY_KEY)
    if company_id:
        company = Company.objects.filter(pk=company_id, is_active=True).first()
        if company and user_membership(request.user, company) is not None:
            return company
        request.session.pop(SESSION_ACTIVE_COMPANY_KEY, None)

    companies = user_companies(request.user)
    if companies.count() == 1:
        company = companies.first()
        if company:
            request.session[SESSION_ACTIVE_COMPANY_KEY] = company.pk
            return company
    return None


def get_enabled_attachment_kinds(company: Company | None) -> set[str]:
    if company is None:
        return set(ATTACHMENT_KIND_CODES)
    enabled = set(
        CompanyAttachmentSetting.objects.filter(
            company=company,
            is_enabled=True,
        ).values_list("attachment_kind", flat=True)
    )
    if not enabled:
        return set(ATTACHMENT_KIND_CODES)
    return enabled


def validate_excel_company_for_tenant(
    company: Company,
    excel_company_names: set[str],
    *,
    locale: str = "en",
) -> None:
    from dashboard_locale import tr

    if not excel_company_names:
        return
    for name in excel_company_names:
        if not company.matches_excel_company(name):
            allowed = ", ".join(company.accepted_excel_names())
            raise ValueError(
                tr(
                    locale,
                    "err_excel_company_mismatch",
                    excel_name=name,
                    company_code=company.code,
                    allowed=allowed,
                )
            )


def extract_excel_company_names_from_df(df, locale: str = "en") -> set[str]:
    from ai_excel_dashboard import _filter_option_token, resolve_audit_observation_columns

    colmap = resolve_audit_observation_columns(df)
    if not colmap or "company" not in colmap:
        return set()
    col = colmap["company"]
    return {
        _filter_option_token(x)
        for x in df[col].dropna().unique()
        if _filter_option_token(x) != ""
    }
