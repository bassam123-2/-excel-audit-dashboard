"""Multi-tenant company access: session company, Excel validation, membership permissions."""
from __future__ import annotations

from django.db.models import Q, QuerySet
from django.utils.translation import gettext_lazy as _

from audit_app.models import (
    ATTACHMENT_KIND_CODES,
    COMPANY_KIND_MAIN,
    COMPANY_KIND_SUBSIDIARY,
    Company,
    CompanyAttachmentSetting,
    CompanyMembership,
    DashboardTemplateType,
    known_template_codes,
)

SESSION_ACTIVE_COMPANY_KEY = "active_company_id"


def active_company_queryset() -> QuerySet[Company]:
    return Company.objects.filter(is_active=True, is_deleted=False)


def active_main_companies() -> QuerySet[Company]:
    return active_company_queryset().filter(
        company_kind=COMPANY_KIND_MAIN,
        parent__isnull=True,
    )


def active_subsidiaries_of(parent: Company) -> QuerySet[Company]:
    return active_company_queryset().filter(
        company_kind=COMPANY_KIND_SUBSIDIARY,
        parent=parent,
    )


def company_is_effectively_active(company: Company | None) -> bool:
    if company is None or not company.is_active or company.is_deleted:
        return False
    if company.parent_id is None:
        return True
    parent = company.parent
    while parent is not None:
        if not parent.is_active or parent.is_deleted:
            return False
        parent = parent.parent
    return True


def tenant_root(company: Company) -> Company:
    return company.tenant_root()


def tenant_company_scope(company: Company) -> QuerySet[Company]:
    root = tenant_root(company)
    return active_company_queryset().filter(Q(pk=root.pk) | Q(parent=root))


def find_company_by_excel_token(
    token: str,
    queryset: QuerySet[Company] | None = None,
) -> Company | None:
    token = str(token or "").strip()
    if not token:
        return None
    qs = queryset if queryset is not None else active_company_queryset()
    for company in qs:
        if company.matches_excel_token(token):
            return company
    return None


def active_companies_exist() -> bool:
    return active_main_companies().exists()


def user_can_manage_companies(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.has_perm("audit_app.add_company") or user.has_perm("audit_app.change_company")


def user_companies(user) -> QuerySet[Company]:
    """Companies the user may select as the active tenant (main companies only)."""
    if not user.is_authenticated:
        return Company.objects.none()
    qs = active_main_companies()
    if user.is_superuser:
        return qs.order_by("code")
    return (
        qs.filter(memberships__user=user)
        .distinct()
        .order_by("code")
    )


def resolve_tenant_company(company: Company | None) -> Company | None:
    """Return the main company that owns uploads/dashboards for this record."""
    if company is None:
        return None
    return tenant_root(company)


def user_membership(user, company: Company | None) -> CompanyMembership | None:
    if not user.is_authenticated or company is None:
        return None
    company = resolve_tenant_company(company)
    if company is None or not company_is_effectively_active(company):
        return None
    if user.is_superuser:
        return CompanyMembership(
            user=user,
            company=company,
            can_upload=True,
            can_assign_dashboard_viewers=True,
            can_view_own_only=False,
            can_review=True,
            can_delete_drafts=True,
        )
    try:
        return CompanyMembership.objects.prefetch_related("template_accesses").get(
            user=user,
            company=company,
            is_deleted=False,
        )
    except CompanyMembership.DoesNotExist:
        return None


def clear_active_company(request) -> None:
    request.session.pop(SESSION_ACTIVE_COMPANY_KEY, None)


def user_must_select_company(user) -> bool:
    return user_companies(user).count() > 1


_PERM_TO_FIELD = {
    "upload": "can_upload",
    "assign_viewers": "can_assign_dashboard_viewers",
    "view_own": "can_view_own_only",
    "review": "can_review",
    "delete_draft": "can_delete_drafts",
}


def _membership_perm_value(
    membership: CompanyMembership,
    field: str,
    template_code: str | None = None,
) -> bool:
    if not membership.pk:
        return bool(getattr(membership, field, False))
    rows = list(membership.template_accesses.all())
    if not rows:
        return bool(getattr(membership, field, False))
    if template_code:
        for row in rows:
            if row.template_code == template_code:
                return bool(getattr(row, field, False))
        return False
    return any(getattr(row, field, False) for row in rows)


def has_company_perm(
    user,
    company: Company | None,
    perm: str,
    template_code: str | None = None,
) -> bool:
    if not user.is_authenticated or not active_companies_exist():
        return False
    if user.is_superuser:
        return True
    if company is None or not company_is_effectively_active(resolve_tenant_company(company)):
        return False
    membership = user_membership(user, company)
    if membership is None:
        return False
    field = _PERM_TO_FIELD.get(perm)
    if not field:
        return False
    return _membership_perm_value(membership, field, template_code)


def template_codes_with_perm(
    user,
    company: Company | None,
    perm: str,
) -> set[str]:
    if not user.is_authenticated or not active_companies_exist():
        return set()
    codes = set(known_template_codes())
    if user.is_superuser:
        return codes
    if company is None or not company_is_effectively_active(resolve_tenant_company(company)):
        return set()
    membership = user_membership(user, company)
    if membership is None:
        return set()
    field = _PERM_TO_FIELD.get(perm)
    if not field:
        return set()
    if not membership.pk:
        return codes if getattr(membership, field, False) else set()
    rows = list(membership.template_accesses.all())
    if not rows:
        return codes if getattr(membership, field, False) else set()
    return {row.template_code for row in rows if getattr(row, field, False)}


def list_nav_template_types():
    types = list(
        DashboardTemplateType.objects.filter(is_active=True, is_deleted=False).order_by(
            "sort_order", "code"
        )
    )
    if types:
        return types
    from audit_app.dashboard_template_codes import TEMPLATE_TYPE_SEEDS

    class _Fallback:
        def __init__(self, seed: dict):
            self.code = seed["code"]
            self.name = seed["name"]
            self.icon = seed.get("icon") or "bi-grid"

    return [_Fallback(seed) for seed in TEMPLATE_TYPE_SEEDS]


def set_active_company(request, company_id: int) -> bool:
    company = active_main_companies().filter(pk=company_id).first()
    if company is None or not company_is_effectively_active(company):
        return False
    if not request.user.is_superuser:
        if not CompanyMembership.objects.filter(
            user=request.user,
            company=company,
            is_deleted=False,
        ).exists():
            return False
    request.session[SESSION_ACTIVE_COMPANY_KEY] = company.pk
    return True


def get_active_company(request) -> Company | None:
    """Return the company stored in session, auto-selecting when the user has only one."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return None

    company_id = request.session.get(SESSION_ACTIVE_COMPANY_KEY)
    if company_id:
        company = active_main_companies().filter(pk=company_id).first()
        if company and company_is_effectively_active(company) and user_membership(request.user, company) is not None:
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
    company = resolve_tenant_company(company)
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


DEFAULT_ATTACHMENT_MAX_FILES = 4
ATTACHMENT_HARD_CEILING = 20


def get_attachment_max_files_map(company: Company | None) -> dict[str, int]:
    """Return max files allowed per attachment kind for the tenant company."""
    defaults = {code: DEFAULT_ATTACHMENT_MAX_FILES for code in ATTACHMENT_KIND_CODES}
    company = resolve_tenant_company(company)
    if company is None:
        return defaults
    for kind, max_files in CompanyAttachmentSetting.objects.filter(
        company=company
    ).values_list("attachment_kind", "max_files"):
        try:
            n = int(max_files)
        except (TypeError, ValueError):
            n = DEFAULT_ATTACHMENT_MAX_FILES
        defaults[str(kind)] = max(1, min(n, ATTACHMENT_HARD_CEILING))
    return defaults


def get_attachment_max_files(company: Company | None, kind: str) -> int:
    return get_attachment_max_files_map(company).get(
        kind, DEFAULT_ATTACHMENT_MAX_FILES
    )


def validate_excel_company_for_tenant(
    company: Company,
    excel_company_names: set[str],
    *,
    locale: str = "en",
) -> None:
    """Raise ValueError if any Excel Company value is not a registered active main company."""
    from dashboard_locale import tr

    if not excel_company_names:
        return
    root = tenant_root(company)
    scope = tenant_company_scope(company).filter(
        company_kind=COMPANY_KIND_MAIN,
        parent__isnull=True,
    )
    allowed_labels = sorted(
        {
            label
            for co in scope
            for label in co.accepted_excel_names() + [co.code, co.name]
            if str(label).strip()
        }
    )
    allowed_display = ", ".join(allowed_labels) if allowed_labels else root.code

    for name in excel_company_names:
        matched = find_company_by_excel_token(name, scope)
        if matched is None:
            raise ValueError(
                tr(
                    locale,
                    "err_excel_company_unregistered",
                    excel_name=name,
                    company_code=root.code,
                    allowed=allowed_display,
                )
            )


def validate_excel_subcompanies_for_tenant(
    company: Company,
    excel_subcompany_names: set[str],
    *,
    locale: str = "en",
) -> None:
    """Raise ValueError if any Excel Subcompany value is not a registered active subsidiary."""
    from dashboard_locale import tr

    if not excel_subcompany_names:
        return
    root = tenant_root(company)
    scope = active_subsidiaries_of(root)
    allowed_labels = sorted(
        {
            label
            for co in scope
            for label in co.accepted_excel_names() + [co.code, co.name]
            if str(label).strip()
        }
    )
    allowed_display = ", ".join(allowed_labels) if allowed_labels else str(_("(none registered)"))

    for name in excel_subcompany_names:
        if root.matches_excel_token(name):
            continue
        matched = find_company_by_excel_token(name, scope)
        if matched is None:
            raise ValueError(
                tr(
                    locale,
                    "err_excel_subcompany_unregistered",
                    excel_name=name,
                    company_code=root.code,
                    allowed=allowed_display,
                )
            )


def _extract_dimension_values_from_df(df, dimension: str) -> set[str]:
    from ai_excel_dashboard import (
        _filter_option_token,
        _norm_audit_header,
        resolve_audit_observation_columns,
    )

    colmap = resolve_audit_observation_columns(df)
    col = colmap.get(dimension) if colmap else None
    if col is None:
        aliases = {
            "company": ("company",),
            "subcompany": ("subcompany", "sub company", "sub-company", "sub_company"),
        }.get(dimension, ())
        n2c = {_norm_audit_header(c): str(c) for c in df.columns}
        for alias in aliases:
            key = _norm_audit_header(alias)
            if key in n2c:
                col = n2c[key]
                break
    if not col:
        return set()
    return {
        _filter_option_token(x)
        for x in df[col].dropna().unique()
        if _filter_option_token(x) != ""
    }


def extract_excel_company_names_from_df(df, locale: str = "en") -> set[str]:
    return _extract_dimension_values_from_df(df, "company")


def extract_excel_subcompany_names_from_df(df, locale: str = "en") -> set[str]:
    return _extract_dimension_values_from_df(df, "subcompany")


def resolve_excel_sheet_for_company(
    path: str,
    company: Company,
    *,
    locale: str = "en",
) -> str | None:
    """
    Prefer a worksheet whose Company column matches the active tenant.

    Workbooks often keep multiple company tabs (e.g. AAGH then BTC). Upload
    previously always used sheet 0, which fails tenant validation. Returns the
    matching sheet name, or the first non-empty sheet when none match.
    """
    import pandas as pd

    from data_io import read_input_file

    ext = str(path).rsplit(".", 1)[-1].lower()
    if ext not in {"xlsx", "xlsm", "xls"}:
        return None

    try:
        xl = pd.ExcelFile(path)
        sheet_names = list(xl.sheet_names)
    except Exception:
        return None
    if not sheet_names:
        return None

    scope = tenant_company_scope(company).filter(
        company_kind=COMPANY_KIND_MAIN,
        parent__isnull=True,
    )
    first_nonempty: str | None = None
    for name in sheet_names:
        try:
            df = read_input_file(path, sheet_name=name, locale=locale)
        except Exception:
            continue
        if isinstance(df, dict):
            continue
        df = df.dropna(how="all").dropna(axis=1, how="all")
        if df.empty:
            continue
        if first_nonempty is None:
            first_nonempty = str(name)
        companies = extract_excel_company_names_from_df(df, locale)
        if not companies:
            continue
        if all(find_company_by_excel_token(n, scope) is not None for n in companies):
            return str(name)
    return first_nonempty
