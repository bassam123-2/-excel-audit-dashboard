"""Django admin for companies, dashboards, memberships, and users."""

from django.contrib import admin, messages
from django.contrib.admin.options import IS_POPUP_VAR, TO_FIELD_VAR
from django.contrib.admin.utils import unquote
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponseRedirect, JsonResponse, QueryDict
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.html import escape, format_html
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from accounts_app.models import UserProfile

from audit_app.dashboard_template_codes import TEMPLATE_CODE_IAD

from .admin_soft_delete import SoftDeleteAdminMixin
from .admin_changelist_v2 import (
    AdminClV2Mixin,
    cl_v2_count_where,
    cl_v2_stat_card,
)
from .admin_utils import (
    company_parent_autocomplete_exclude_pk,
    format_admin_active_status_icon,
    format_admin_boolean_icon,
    install_boolean_icon_list_columns,
)
from .admin_forms import (
    AdminUserChangeForm,
    CompanyAdminForm,
    MandatoryPasswordAdminChangeForm,
    MandatoryPasswordAdminCreationForm,
    apply_user_profile_form,
    company_attachment_field_name,
)
from .models import (
    ATTACHMENT_KIND_CODES,
    COMPANY_KIND_MAIN,
    COMPANY_KIND_SUBSIDIARY,
    Company,
    CompanyAttachmentSetting,
    CompanyMembership,
    CompanyLogo,
    Dashboard,
    DashboardRejectionLog,
    DashboardStatus,
    DashboardTemplateType,
    ObservationRecord,
    ReportArtifact,
    UploadSession,
)

# ── Protected User Admin ─────────────────────────────────────────────

DASHBOARD_LEGACY_PERMISSION_CODENAMES = (
    "can_upload_files",
    "can_view_dashboards",
    "can_review_dashboards",
    "can_delete_dashboards",
)
DASHBOARD_AUTH_MODEL = "dashboard"


def permissions_queryset_without_dashboard_legacy():
    """Hide all Dashboard model auth permissions; use Company memberships instead."""
    return Permission.objects.exclude(
        content_type__app_label="audit_app",
        content_type__model=DASHBOARD_AUTH_MODEL,
    )


class DeletedUserFilter(admin.SimpleListFilter):
    title = _("Deletion status")
    parameter_name = "deleted"

    def lookups(self, request, model_admin):
        choices = [
            ("active", _("Active users")),
            ("deleted", _("Deleted users")),
        ]
        if model_admin.can_view_deleted_users(request):
            choices.insert(0, ("all", _("All")))
        return tuple(choices)

    def queryset(self, request, queryset):
        value = self.value() or "active"
        if value == "all":
            if request.user.has_perm("auth.delete_user") or request.user.is_superuser:
                return queryset
            value = "active"
        if value == "deleted":
            return queryset.filter(profile__is_deleted=True)
        return queryset.filter(
            Q(profile__is_deleted=False) | Q(profile__isnull=True)
        )

    def choices(self, changelist):
        request = self.request
        model_admin = changelist.model_admin
        value = self.value() or "active"
        can_view_all = model_admin.can_view_deleted_users(request)

        if can_view_all:
            yield {
                "selected": value == "all",
                "query_string": changelist.get_query_string(
                    {self.parameter_name: "all"}
                ),
                "display": _("All"),
            }

        yield {
            "selected": value == "active",
            "query_string": changelist.get_query_string(
                {self.parameter_name: "active"}
            ),
            "display": _("Active users"),
        }
        yield {
            "selected": value == "deleted",
            "query_string": changelist.get_query_string(
                {self.parameter_name: "deleted"}
            ),
            "display": _("Deleted users"),
        }


class TwoFactorFilter(admin.SimpleListFilter):
    title = _("Two-factor authentication")
    parameter_name = "two_factor"

    def lookups(self, request, model_admin):
        return (
            ("yes", _("Enabled")),
            ("no", _("Disabled")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.filter(profile__two_factor_enabled=True)
        if value == "no":
            return queryset.filter(
                Q(profile__two_factor_enabled=False) | Q(profile__isnull=True)
            )
        return queryset


class PasswordExpiryFilter(admin.SimpleListFilter):
    title = _("6-month password expiry")
    parameter_name = "password_expiry"

    def lookups(self, request, model_admin):
        return (
            ("yes", _("Enabled")),
            ("no", _("Disabled")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.filter(profile__password_expiry_enabled=True)
        if value == "no":
            return queryset.filter(
                Q(profile__password_expiry_enabled=False) | Q(profile__isnull=True)
            )
        return queryset


class WorkflowEmailsFilter(admin.SimpleListFilter):
    title = _("Workflow notification emails")
    parameter_name = "workflow_emails"

    def lookups(self, request, model_admin):
        return (
            ("yes", _("Enabled")),
            ("no", _("Disabled")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.filter(profile__receive_workflow_emails=True)
        if value == "no":
            return queryset.filter(
                Q(profile__receive_workflow_emails=False) | Q(profile__isnull=True)
            )
        return queryset


class CompanyMembershipInline(admin.TabularInline):
    model = CompanyMembership
    extra = 1
    autocomplete_fields = ("company",)
    fk_name = "user"
    fields = (
        "company",
        "can_upload",
        "can_assign_dashboard_viewers",
        "can_view_own_only",
        "can_review",
        "can_delete_drafts",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).filter(is_deleted=False)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "company":
            from audit_app.company_access import active_main_companies

            kwargs["queryset"] = active_main_companies().order_by("code")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class ProtectedUserAdmin(AdminClV2Mixin, BaseUserAdmin):
    """
    Blocks any modification or deletion of the default superadmin account ('myadmin').
    All other users can be managed normally by staff with user-management permissions.
    Password-based authentication is always required (no disable-password option).
    User deletion is soft — records stay in the database and can be restored.

    Dashboard upload/view/review/draft-delete are configured in Company memberships
    (inline below), not via Groups or User permissions.
    """

    PROTECTED_USERNAME = "myadmin"
    CL_V2_QUICK_ACTIONS = (
        "enable_two_factor_selected",
        "disable_two_factor_selected",
        "enable_password_expiry_selected",
        "disable_password_expiry_selected",
        "enable_workflow_emails_selected",
        "disable_workflow_emails_selected",
    )
    CL_V2_QUICK_ACTION_ICONS = {
        "enable_two_factor_selected": "bi-shield-lock",
        "disable_two_factor_selected": "bi-shield-slash",
        "enable_password_expiry_selected": "bi-clock-history",
        "disable_password_expiry_selected": "bi-clock",
        "enable_workflow_emails_selected": "bi-envelope-check",
        "disable_workflow_emails_selected": "bi-envelope-slash",
    }
    form = AdminUserChangeForm
    add_form = MandatoryPasswordAdminCreationForm
    add_form_template = "admin/auth/user/change_form.html"
    change_form_template = "admin/auth/user/change_form.html"
    inlines = [CompanyMembershipInline]
    delete_confirmation_template = "admin/auth/user/delete_confirmation.html"
    delete_selected_confirmation_template = "admin/auth/user/delete_selected_confirmation.html"
    cl_v2_default_filter_params = {"deleted": "active"}
    readonly_fields = ("last_login", "date_joined")
    actions = [
        "restore_users",
        "enable_two_factor_selected",
        "disable_two_factor_selected",
        "enable_two_factor_all",
        "disable_two_factor_all",
        "enable_password_expiry_selected",
        "disable_password_expiry_selected",
        "enable_password_expiry_all",
        "disable_password_expiry_all",
        "enable_workflow_emails_selected",
        "disable_workflow_emails_selected",
        "enable_workflow_emails_all",
        "disable_workflow_emails_all",
        "export_users_csv",
    ]
    list_filter = BaseUserAdmin.list_filter + (
        DeletedUserFilter,
        TwoFactorFilter,
        PasswordExpiryFilter,
        WorkflowEmailsFilter,
    )

    class Media:
        css = {"all": ("css/password_rules.css",)}
        js = (
            "js/password_rules.js",
            "js/admin_email_validate.js",
            "js/admin_password_generate.js",
        )

    list_display = (
        "username",
        "active_status_display",
        "full_name_display",
        "email",
        "job_title_display",
        "staff_status_display",
        "two_factor_display",
        "password_expiry_display",
        "workflow_emails_display",
    )
    search_fields = BaseUserAdmin.search_fields + ("profile__job_title",)

    def get_search_results(self, request, queryset, search_term):
        """Search across all user text fields shown in the changelist."""
        if not search_term:
            return queryset, False
        term = search_term.strip()
        if not term:
            return queryset, False
        from django.db.models import Q

        qs = queryset.filter(
            Q(username__icontains=term)
            | Q(first_name__icontains=term)
            | Q(last_name__icontains=term)
            | Q(email__icontains=term)
            | Q(profile__job_title__icontains=term)
        )
        return qs, True

    cl_v2_subtitle = _("Browse, search, and filter all system users from one place.")

    def get_cl_v2_form_subtitle(self, request, obj=None, add=False):
        if add:
            return _(
                "Create a new user account, set permissions, and assign company memberships."
            )
        return _("Update user profile, permissions, password, and company access.")

    def get_cl_v2_search_placeholder(self, request):
        return _("Search username, name, email, or job title…")

    def get_cl_v2_stat_cards(self, request, queryset):
        return [
            {
                "label": _("Total users"),
                "value": queryset.count(),
                "icon": "bi-people-fill",
                "tone": "primary",
            },
            {
                "label": _("Active"),
                "value": queryset.filter(is_active=True).count(),
                "icon": "bi-person-check-fill",
                "tone": "success",
            },
            {
                "label": _("Staff"),
                "value": queryset.filter(is_staff=True).count(),
                "icon": "bi-person-badge-fill",
                "tone": "info",
            },
            {
                "label": _("2FA enabled"),
                "value": queryset.filter(profile__two_factor_enabled=True).count(),
                "icon": "bi-shield-lock-fill",
                "tone": "warning",
            },
        ]

    def can_view_deleted_users(self, request) -> bool:
        return request.user.has_perm("auth.delete_user") or request.user.is_superuser

    fieldsets = (
        (None, {"fields": ("username",)}),
        (_("Personal info"), {
            "fields": (
                "first_name",
                "last_name",
                "email",
                "job_title",
                "two_factor_enabled",
                "password_expiry_enabled",
                "receive_workflow_emails",
            ),
        }),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2"),
            },
        ),
        (
            _("Personal info"),
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "email",
                    "job_title",
                    "two_factor_enabled",
                    "password_expiry_enabled",
                ),
            },
        ),
    )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if isinstance(form, (MandatoryPasswordAdminCreationForm, AdminUserChangeForm)):
            apply_user_profile_form(form.instance, form.cleaned_data)

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets
        fieldsets = super().get_fieldsets(request, obj)
        if request.user.is_superuser:
            return fieldsets
        cleaned = []
        for name, opts in fieldsets:
            fields = tuple(
                f for f in opts.get("fields", ()) if f != "user_permissions"
            )
            cleaned.append((name, {**opts, "fields": fields}))
        return cleaned

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "user_permissions":
            kwargs["queryset"] = permissions_queryset_without_dashboard_legacy()
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def get_urls(self):
        from django.contrib.admin.views.autocomplete import AutocompleteJsonView

        from audit_app.admin_utils import format_admin_user_label

        class AdminUserAutocompleteJsonView(AutocompleteJsonView):
            def serialize_result(self, obj, to_field_name):
                return {
                    "id": str(getattr(obj, to_field_name)),
                    "text": format_admin_user_label(obj),
                }

        info = self.model._meta.app_label, self.model._meta.model_name
        autocomplete_name = "%s_%s_autocomplete" % info
        urls = self.get_cl_v2_urls() + [
            path(
                "generate-password/",
                self.admin_site.admin_view(self.generate_password_view),
                name="%s_%s_generate_password"
                % (self.model._meta.app_label, self.model._meta.model_name),
            ),
            path(
                "<id>/set-password/",
                self.admin_site.admin_view(self.user_set_password),
                name="%s_%s_set_password"
                % (self.model._meta.app_label, self.model._meta.model_name),
            ),
            path(
                "autocomplete/",
                self.admin_site.admin_view(
                    AdminUserAutocompleteJsonView.as_view(admin_site=self.admin_site)
                ),
                name=autocomplete_name,
            ),
        ]
        for url_pattern in admin.ModelAdmin.get_urls(self):
            if url_pattern.name == autocomplete_name:
                continue
            urls.append(url_pattern)
        return urls

    def generate_password_view(self, request):
        if not request.user.is_staff:
            raise PermissionDenied
        from accounts_app.services.password_generator import generate_compliant_password

        return JsonResponse({"password": generate_compliant_password()})

    def _send_credentials_email(self, request, user, raw_password: str) -> bool:
        del raw_password  # password is never sent by email; user sets it via one-time link
        from ai_excel_dashboard import load_smtp_config

        from accounts_app.services.credentials_email import send_credentials_email_smtp
        from accounts_app.services.email_branding import resolve_logo_src_for_email
        from accounts_app.services.password_set_token import (
            build_set_password_url,
            create_password_set_token,
        )

        email = (user.email or "").strip()
        if not email:
            self.message_user(
                request,
                _("No email address — credentials were not sent."),
                messages.WARNING,
            )
            return False
        cfg = load_smtp_config()
        if not cfg:
            self.message_user(
                request,
                _("SMTP is not configured — credentials were not sent."),
                messages.WARNING,
            )
            return False
        try:
            token = create_password_set_token(user)
            set_password_url = build_set_password_url(
                token,
                base_url=request.build_absolute_uri("/"),
            )
            send_credentials_email_smtp(
                cfg,
                to_addr=email,
                username=user.username,
                set_password_url=set_password_url,
                logo_url=resolve_logo_src_for_email(
                    base_url=request.build_absolute_uri("/"),
                    cfg=cfg,
                ),
            )
            return True
        except ValueError as exc:
            if str(exc) == "insecure_email_base_url":
                self.message_user(
                    request,
                    _(
                        "Cannot send credentials email: configure PUBLIC_SITE_URL "
                        "with HTTPS for production links."
                    ),
                    messages.WARNING,
                )
            else:
                self.message_user(
                    request,
                    _("Failed to send credentials email."),
                    messages.WARNING,
                )
            return False
        except Exception:
            self.message_user(
                request,
                _("Failed to send credentials email."),
                messages.WARNING,
            )
            return False

    def save_model(self, request, obj, form, change):
        send_credentials = False
        raw_password = ""
        if not change and isinstance(form, MandatoryPasswordAdminCreationForm):
            send_credentials = bool(form.cleaned_data.get("send_credentials_email"))
            raw_password = form.cleaned_data.get("password1") or ""
        if change and self._is_soft_deleted(obj):
            obj.is_active = False
        super().save_model(request, obj, form, change)
        if not change:
            profile, _created = UserProfile.objects.get_or_create(user=obj)
            profile.must_change_password_on_login = True
            profile.save(update_fields=["must_change_password_on_login"])
            if send_credentials and raw_password:
                if self._send_credentials_email(request, obj, raw_password):
                    self.message_user(
                        request,
                        _("Login credentials were sent by email."),
                        messages.SUCCESS,
                    )

    @method_decorator(sensitive_post_parameters("password1", "password2"))
    @method_decorator(csrf_protect)
    def user_set_password(self, request, id):
        obj = self.get_object(request, unquote(id))
        if obj is None:
            raise Http404(
                _("%(name)s object with primary key %(key)r does not exist.")
                % {"name": self.opts.verbose_name, "key": escape(id)}
            )
        if not self.has_change_permission(request, obj):
            raise PermissionDenied

        if request.method != "POST":
            return HttpResponseRedirect(
                reverse(
                    f"admin:{self.opts.app_label}_{self.opts.model_name}_change",
                    args=(obj.pk,),
                )
            )

        form = MandatoryPasswordAdminChangeForm(obj, request.POST)
        if form.is_valid():
            user = form.save()
            profile, _created = UserProfile.objects.get_or_create(user=user)
            profile.password_changed_at = timezone.now()
            profile.must_change_password_on_login = True
            profile.save(
                update_fields=["password_changed_at", "must_change_password_on_login"]
            )
            raw_password = form.cleaned_data.get("password1") or ""
            credentials_sent = False
            if form.cleaned_data.get("send_credentials_email") and raw_password:
                credentials_sent = self._send_credentials_email(request, user, raw_password)
                if credentials_sent:
                    self.message_user(
                        request,
                        _("New password was sent by email."),
                        messages.SUCCESS,
                    )
            change_msg = [{"changed": {"fields": ["password"]}}]
            if credentials_sent:
                change_msg[0]["credentials_email_sent"] = True
            self.log_change(request, user, change_msg)
            if request.user.pk == user.pk:
                update_session_auth_hash(request, user)
            self.message_user(
                request,
                gettext("Password changed successfully."),
                messages.SUCCESS,
            )
            return HttpResponseRedirect(
                reverse(
                    f"admin:{self.opts.app_label}_{self.opts.model_name}_change",
                    args=(obj.pk,),
                )
            )

        extra_context = {
            "password_form": form,
            "password_form_invalid": True,
            "user_is_soft_deleted": self._is_soft_deleted(obj),
        }
        saved_post = request.POST
        request.POST = QueryDict()
        request.method = "GET"
        try:
            return self.changeform_view(
                request,
                str(obj.pk),
                "",
                extra_context=extra_context,
            )
        finally:
            request.POST = saved_post
            request.method = "POST"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("profile")

    def _is_protected(self, obj) -> bool:
        return obj is not None and (
            obj.username == self.PROTECTED_USERNAME or obj.is_superuser
        )

    def _is_soft_deleted(self, obj) -> bool:
        profile = getattr(obj, "profile", None)
        return bool(profile and profile.is_deleted)

    def _soft_delete_user(self, user) -> None:
        profile, _created = UserProfile.objects.get_or_create(user=user)
        profile.is_deleted = True
        profile.deleted_at = timezone.now()
        profile.save(update_fields=["is_deleted", "deleted_at"])
        if user.is_active:
            user.is_active = False
            user.save(update_fields=["is_active"])

    def _restore_user(self, user) -> None:
        profile, _created = UserProfile.objects.get_or_create(user=user)
        profile.is_deleted = False
        profile.deleted_at = None
        profile.save(update_fields=["is_deleted", "deleted_at"])
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=["is_active"])

    def has_change_permission(self, request, obj=None):
        if self._is_protected(obj) and not request.user.username == self.PROTECTED_USERNAME:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self._is_protected(obj):
            return False
        if obj is not None and self._is_soft_deleted(obj):
            return False
        return super().has_delete_permission(request, obj)

    def has_restore_permission(self, request, obj=None) -> bool:
        if self._is_protected(obj):
            return False
        return request.user.has_perm("auth.delete_user") or request.user.is_superuser

    def get_readonly_fields(self, request, obj=None):
        rf = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            rf += ["is_superuser", "user_permissions"]
        if not self._can_manage_user_security(request):
            rf += [
                "two_factor_enabled",
                "password_expiry_enabled",
                "receive_workflow_emails",
            ]
        if obj is not None and self._is_soft_deleted(obj):
            rf.append("is_active")
        return rf

    def _can_manage_user_security(self, request) -> bool:
        return request.user.is_superuser or request.user.has_perm("auth.change_user")

    def _can_manage_two_factor(self, request) -> bool:
        return self._can_manage_user_security(request)

    @admin.display(description=_("Active"), ordering="is_active")
    def active_status_display(self, obj):
        return format_admin_active_status_icon(obj.is_active)

    @admin.display(description=_("Staff status"), ordering="is_staff")
    def staff_status_display(self, obj):
        return format_admin_boolean_icon(
            obj.is_staff,
            yes_label=_("Yes"),
            no_label=_("No"),
        )

    @admin.display(description=_("2FA"), ordering="profile__two_factor_enabled")
    def two_factor_display(self, obj):
        profile = getattr(obj, "profile", None)
        return format_admin_boolean_icon(
            bool(profile and profile.two_factor_enabled),
            yes_label=_("Enabled"),
            no_label=_("Disabled"),
        )

    @admin.display(
        description=_("Pwd expiry"),
        ordering="profile__password_expiry_enabled",
    )
    def password_expiry_display(self, obj):
        profile = getattr(obj, "profile", None)
        return format_admin_boolean_icon(
            bool(profile and profile.password_expiry_enabled),
            yes_label=_("Enabled"),
            no_label=_("Disabled"),
        )

    @admin.display(
        description=_("Workflow emails"),
        ordering="profile__receive_workflow_emails",
    )
    def workflow_emails_display(self, obj):
        profile = getattr(obj, "profile", None)
        return format_admin_boolean_icon(
            bool(profile and profile.receive_workflow_emails),
            yes_label=_("Enabled"),
            no_label=_("Disabled"),
        )

    @admin.action(description=_("Enable email 2FA for selected users"))
    def enable_two_factor_selected(self, request, queryset):
        if not self._can_manage_two_factor(request):
            self.message_user(request, _("Permission denied."), messages.ERROR)
            return
        count = UserProfile.bulk_set_two_factor(enabled=True, users=queryset)
        self.message_user(
            request,
            _("Email two-factor authentication enabled for %(count)d user(s).")
            % {"count": count},
            messages.SUCCESS,
        )

    @admin.action(description=_("Disable email 2FA for selected users"))
    def disable_two_factor_selected(self, request, queryset):
        if not self._can_manage_two_factor(request):
            self.message_user(request, _("Permission denied."), messages.ERROR)
            return
        count = UserProfile.bulk_set_two_factor(enabled=False, users=queryset)
        self.message_user(
            request,
            _("Email two-factor authentication disabled for %(count)d user(s).")
            % {"count": count},
            messages.SUCCESS,
        )

    @admin.action(description=_("Enable email 2FA for ALL users"))
    def enable_two_factor_all(self, request, queryset):
        if not request.user.is_superuser:
            self.message_user(
                request,
                _("Only a superuser can change 2FA for all users."),
                messages.ERROR,
            )
            return
        count = UserProfile.bulk_set_two_factor(enabled=True)
        self.message_user(
            request,
            _("Email two-factor authentication enabled for %(count)d user(s).")
            % {"count": count},
            messages.SUCCESS,
        )

    @admin.action(description=_("Disable email 2FA for ALL users"))
    def disable_two_factor_all(self, request, queryset):
        if not request.user.is_superuser:
            self.message_user(
                request,
                _("Only a superuser can change 2FA for all users."),
                messages.ERROR,
            )
            return
        count = UserProfile.bulk_set_two_factor(enabled=False)
        self.message_user(
            request,
            _("Email two-factor authentication disabled for %(count)d user(s).")
            % {"count": count},
            messages.SUCCESS,
        )

    @admin.action(description=_("Enable 6-month password expiry for selected users"))
    def enable_password_expiry_selected(self, request, queryset):
        if not self._can_manage_user_security(request):
            self.message_user(request, _("Permission denied."), messages.ERROR)
            return
        count = UserProfile.bulk_set_password_expiry(enabled=True, users=queryset)
        self.message_user(
            request,
            _("6-month password expiry enabled for %(count)d user(s).") % {"count": count},
            messages.SUCCESS,
        )

    @admin.action(description=_("Disable 6-month password expiry for selected users"))
    def disable_password_expiry_selected(self, request, queryset):
        if not self._can_manage_user_security(request):
            self.message_user(request, _("Permission denied."), messages.ERROR)
            return
        count = UserProfile.bulk_set_password_expiry(enabled=False, users=queryset)
        self.message_user(
            request,
            _("6-month password expiry disabled for %(count)d user(s).") % {"count": count},
            messages.SUCCESS,
        )

    @admin.action(description=_("Enable 6-month password expiry for ALL users"))
    def enable_password_expiry_all(self, request, queryset):
        if not request.user.is_superuser:
            self.message_user(
                request,
                _("Only a superuser can change password expiry for all users."),
                messages.ERROR,
            )
            return
        count = UserProfile.bulk_set_password_expiry(enabled=True)
        self.message_user(
            request,
            _("6-month password expiry enabled for %(count)d user(s).") % {"count": count},
            messages.SUCCESS,
        )

    @admin.action(description=_("Disable 6-month password expiry for ALL users"))
    def disable_password_expiry_all(self, request, queryset):
        if not request.user.is_superuser:
            self.message_user(
                request,
                _("Only a superuser can change password expiry for all users."),
                messages.ERROR,
            )
            return
        count = UserProfile.bulk_set_password_expiry(enabled=False)
        self.message_user(
            request,
            _("6-month password expiry disabled for %(count)d user(s).") % {"count": count},
            messages.SUCCESS,
        )

    @admin.action(description=_("Enable workflow notification emails for selected users"))
    def enable_workflow_emails_selected(self, request, queryset):
        if not self._can_manage_user_security(request):
            self.message_user(request, _("Permission denied."), messages.ERROR)
            return
        count = UserProfile.bulk_set_receive_workflow_emails(enabled=True, users=queryset)
        self.message_user(
            request,
            _("Workflow notification emails enabled for %(count)d user(s).")
            % {"count": count},
            messages.SUCCESS,
        )

    @admin.action(description=_("Disable workflow notification emails for selected users"))
    def disable_workflow_emails_selected(self, request, queryset):
        if not self._can_manage_user_security(request):
            self.message_user(request, _("Permission denied."), messages.ERROR)
            return
        count = UserProfile.bulk_set_receive_workflow_emails(enabled=False, users=queryset)
        self.message_user(
            request,
            _("Workflow notification emails disabled for %(count)d user(s).")
            % {"count": count},
            messages.SUCCESS,
        )

    @admin.action(description=_("Enable workflow notification emails for ALL users"))
    def enable_workflow_emails_all(self, request, queryset):
        if not request.user.is_superuser:
            self.message_user(
                request,
                _("Only a superuser can change workflow emails for all users."),
                messages.ERROR,
            )
            return
        count = UserProfile.bulk_set_receive_workflow_emails(enabled=True)
        self.message_user(
            request,
            _("Workflow notification emails enabled for %(count)d user(s).")
            % {"count": count},
            messages.SUCCESS,
        )

    @admin.action(description=_("Disable workflow notification emails for ALL users"))
    def disable_workflow_emails_all(self, request, queryset):
        if not request.user.is_superuser:
            self.message_user(
                request,
                _("Only a superuser can change workflow emails for all users."),
                messages.ERROR,
            )
            return
        count = UserProfile.bulk_set_receive_workflow_emails(enabled=False)
        self.message_user(
            request,
            _("Workflow notification emails disabled for %(count)d user(s).")
            % {"count": count},
            messages.SUCCESS,
        )

    @admin.action(description=_("Export selected users (CSV)"))
    def export_users_csv(self, request, queryset):
        import csv

        from django.http import HttpResponse

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="users.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "username",
                "email",
                "first_name",
                "last_name",
                "job_title",
                "is_active",
                "is_staff",
                "date_joined",
            ]
        )
        for user in queryset.select_related("profile"):
            profile = getattr(user, "profile", None)
            writer.writerow(
                [
                    user.username,
                    user.email,
                    user.first_name,
                    user.last_name,
                    profile.job_title if profile else "",
                    user.is_active,
                    user.is_staff,
                    user.date_joined.isoformat() if user.date_joined else "",
                ]
            )
        return response

    @admin.display(description=_("Name"), ordering="first_name")
    def full_name_display(self, obj):
        full = obj.get_full_name().strip()
        return full or "—"

    @admin.display(description=_("Job title"), ordering="profile__job_title")
    def job_title_display(self, obj):
        profile = getattr(obj, "profile", None)
        return profile.job_title if profile and profile.job_title else "—"

    @admin.action(description=_("Restore selected users"))
    def restore_users(self, request, queryset):
        if not self.has_restore_permission(request):
            self.message_user(request, _("Permission denied."), messages.ERROR)
            return
        restored = 0
        for user in queryset.select_related("profile"):
            if self._is_protected(user) or not self._is_soft_deleted(user):
                continue
            self._restore_user(user)
            restored += 1
        if restored:
            self.message_user(
                request,
                gettext("%(count)d user(s) were restored successfully.")
                % {"count": restored},
                messages.SUCCESS,
            )

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not self.has_restore_permission(request):
            actions.pop("restore_users", None)
        return actions

    def delete_model(self, request, obj):
        self._soft_delete_user(obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            if not self._is_protected(obj):
                self._soft_delete_user(obj)

    def delete_view(self, request, object_id, extra_context=None):
        obj = self.get_object(request, unquote(object_id))
        if obj is None:
            return self._get_obj_does_not_exist_redirect(request, self.opts, object_id)

        if not self.has_delete_permission(request, obj):
            raise PermissionDenied

        if request.method == "POST":
            self._soft_delete_user(obj)
            self.log_deletions(request, self.model.objects.filter(pk=obj.pk))
            self.message_user(
                request,
                gettext('The user "%(name)s" was removed successfully.')
                % {"name": obj.get_username()},
                messages.SUCCESS,
            )
            return HttpResponseRedirect(
                reverse(
                    f"admin:{self.opts.app_label}_{self.opts.model_name}_changelist",
                    current_app=self.admin_site.name,
                )
            )

        context = {
            **self.admin_site.each_context(request),
            "title": _("Remove user"),
            "object": obj,
            "object_name": _("user"),
            "opts": self.opts,
            "deleted_objects": [],
            "model_count": {},
            "perms_lacking": set(),
            "protected": [],
            "is_popup": IS_POPUP_VAR in request.POST or IS_POPUP_VAR in request.GET,
            "is_popup_var": IS_POPUP_VAR,
            "to_field_var": TO_FIELD_VAR,
            "to_field": request.POST.get(TO_FIELD_VAR) or request.GET.get(TO_FIELD_VAR),
            **(extra_context or {}),
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(
            request,
            self.delete_confirmation_template or [
                "admin/{}/{}/delete_confirmation.html".format(
                    self.opts.app_label, self.opts.model_name
                ),
                "admin/delete_confirmation.html",
            ],
            context,
        )

    def response_change(self, request, obj):
        if "_restore" in request.POST:
            if not self.has_restore_permission(request, obj):
                raise PermissionDenied
            if not self._is_protected(obj) and self._is_soft_deleted(obj):
                self._restore_user(obj)
                self.message_user(
                    request,
                    gettext('The user "%(name)s" was restored successfully.')
                    % {"name": obj.get_username()},
                    messages.SUCCESS,
                )
            return HttpResponseRedirect(
                reverse(
                    f"admin:{self.opts.app_label}_{self.opts.model_name}_change",
                    args=(obj.pk,),
                    current_app=self.admin_site.name,
                )
            )
        return super().response_change(request, obj)

    def render_change_form(
        self, request, context, add=False, change=False, form_url="", obj=None
    ):
        if change and obj is not None:
            context.setdefault(
                "password_form",
                MandatoryPasswordAdminChangeForm(obj),
            )
            context.setdefault(
                "user_is_soft_deleted",
                self._is_soft_deleted(obj),
            )
            context.setdefault(
                "can_restore_user",
                self._is_soft_deleted(obj) and self.has_restore_permission(request, obj),
            )
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url, obj=obj
        )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, unquote(object_id))
        if obj is not None:
            extra_context["user_is_soft_deleted"] = self._is_soft_deleted(obj)
            extra_context["can_restore_user"] = (
                self._is_soft_deleted(obj) and self.has_restore_permission(request, obj)
            )
            extra_context.setdefault(
                "password_form",
                MandatoryPasswordAdminChangeForm(obj),
            )
        return super().change_view(request, object_id, form_url, extra_context)


class ProtectedGroupAdmin(AdminClV2Mixin, BaseGroupAdmin):
    """Hide legacy dashboard permissions — use Company memberships instead."""

    def has_delete_permission(self, request, obj=None):
        return False

    cl_v2_subtitle = _("Manage permission groups and assign capabilities to users.")

    def get_cl_v2_form_subtitle(self, request, obj=None, add=False):
        if add:
            return _("Create a permission group and assign capabilities to users.")
        return _("Edit group name and assigned permissions.")

    def get_cl_v2_search_placeholder(self, request):
        return _("Search group name…")

    def get_cl_v2_stat_cards(self, request, queryset):
        with_members = queryset.annotate(_member_count=Count("user")).filter(
            _member_count__gt=0
        ).count()
        with_permissions = queryset.annotate(_perm_count=Count("permissions")).filter(
            _perm_count__gt=0
        ).count()
        return [
            cl_v2_stat_card(_("Total groups"), queryset.count(), icon="bi-people-fill"),
            cl_v2_stat_card(
                _("With members"),
                with_members,
                icon="bi-person-check-fill",
                tone="success",
            ),
            cl_v2_stat_card(
                _("With permissions"),
                with_permissions,
                icon="bi-shield-check",
                tone="info",
            ),
            cl_v2_stat_card(
                _("Empty groups"),
                queryset.count() - with_members,
                icon="bi-person-dash-fill",
                tone="warning",
            ),
        ]

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "permissions":
            kwargs["queryset"] = permissions_queryset_without_dashboard_legacy()
        return super().formfield_for_manytomany(db_field, request, **kwargs)


admin.site.unregister(User)
admin.site.register(User, ProtectedUserAdmin)
admin.site.unregister(Group)
admin.site.register(Group, ProtectedGroupAdmin)


# ── App models ───────────────────────────────────────────────────────


class ActiveCompanyFkMixin:
    """Limit company foreign-key widgets to active main companies (tenant scope)."""

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "company":
            from audit_app.company_access import active_main_companies

            kwargs["queryset"] = active_main_companies().order_by("code")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Company)
class CompanyAdmin(SoftDeleteAdminMixin, AdminClV2Mixin, admin.ModelAdmin):
    soft_delete_deactivate_active_field = "is_active"
    form = CompanyAdminForm
    cl_v2_subtitle = _(
        "Browse and manage all companies (active and inactive) from one place."
    )
    list_display = ("code", "active_status_display", "name", "company_kind", "parent", "created_at")
    list_display_links = ("code",)
    search_fields = ("code", "name")
    list_filter = ("is_active", "company_kind")
    prepopulated_fields = {"code": ("name",)}
    autocomplete_fields = ("parent",)
    readonly_fields = ("logo_preview",)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "code",
                    "name",
                    "company_kind",
                    "parent",
                    "logo",
                    "logo_preview",
                    "is_active",
                )
            },
        ),
        (_("Excel mapping"), {"fields": ("excel_company_names",)}),
        (
            _("Workflow"),
            {"fields": ("use_workflow_v2", "notify_creator_on_publish")},
        ),
        (
            _("Attachments (enable or disable per company)"),
            {
                "fields": [
                    company_attachment_field_name(code)
                    for code in ATTACHMENT_KIND_CODES
                ],
            },
        ),
    )

    def get_fieldsets(self, request, obj=None):
        fieldsets = list(super().get_fieldsets(request, obj))
        kind = request.POST.get("company_kind") if request.method == "POST" else None
        if (obj and obj.is_subsidiary) or kind == "subsidiary":
            fieldsets = [
                fs
                for fs in fieldsets
                if fs[0] != _("Attachments (enable or disable per company)")
            ]
        return fieldsets

    class Media:
        js = ("js/admin_company_form.js",)

    def logo_preview(self, obj):
        if obj and obj.logo:
            return format_html(
                '<img src="{}" alt="" style="max-height:80px;max-width:200px;">',
                obj.logo.url,
            )
        return "—"

    logo_preview.short_description = _("Logo preview")

    @admin.display(description=_("Status"), ordering="is_active")
    def active_status_display(self, obj):
        return format_admin_active_status_icon(obj.is_active)

    def get_cl_v2_search_placeholder(self, request):
        return _("Search company code or name…")

    def get_cl_v2_stat_cards(self, request, queryset):
        return [
            {
                "label": _("Total companies"),
                "value": queryset.count(),
                "icon": "bi-building-fill",
                "tone": "primary",
            },
            {
                "label": _("Active"),
                "value": queryset.filter(is_active=True).count(),
                "icon": "bi-check-circle-fill",
                "tone": "success",
            },
            {
                "label": _("Main companies"),
                "value": queryset.filter(company_kind=COMPANY_KIND_MAIN).count(),
                "icon": "bi-diagram-3-fill",
                "tone": "info",
            },
            {
                "label": _("Subsidiaries"),
                "value": queryset.filter(company_kind=COMPANY_KIND_SUBSIDIARY).count(),
                "icon": "bi-diagram-2-fill",
                "tone": "warning",
            },
        ]

    def get_search_results(self, request, queryset, search_term):
        """Changelist search includes inactive companies; autocomplete keeps active only."""
        if "/autocomplete/" in request.path:
            app_label = request.GET.get("app_label")
            model_name = request.GET.get("model_name")
            field_name = request.GET.get("field_name")

            if app_label == "audit_app" and (
                (model_name == "company" and field_name == "parent")
                or (model_name == "companymembership" and field_name == "company")
            ):
                from audit_app.company_access import active_main_companies

                queryset = active_main_companies()
                if model_name == "company" and field_name == "parent":
                    exclude_pk = company_parent_autocomplete_exclude_pk(request)
                    if exclude_pk is not None:
                        queryset = queryset.exclude(pk=exclude_pk)
            else:
                queryset = queryset.filter(is_active=True, is_deleted=False)
        return super().get_search_results(request, queryset, search_term)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "parent":
            from audit_app.company_access import active_main_companies

            kwargs["queryset"] = active_main_companies().order_by("code")
            formfield = super().formfield_for_foreignkey(db_field, request, **kwargs)
            object_id = (
                request.resolver_match.kwargs.get("object_id")
                if request.resolver_match
                else None
            )
            if object_id:
                formfield.widget.attrs["data-exclude-pk"] = str(unquote(object_id))
            return formfield
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        form.save_attachment_settings(obj)


@admin.register(CompanyMembership)
class CompanyMembershipAdmin(SoftDeleteAdminMixin, AdminClV2Mixin, ActiveCompanyFkMixin, admin.ModelAdmin):
    cl_v2_subtitle = _(
        "Manage user access, upload rights, and review permissions per company."
    )
    _MEMBERSHIP_BOOL_FIELDS = (
        "can_upload",
        "can_assign_dashboard_viewers",
        "can_view_own_only",
        "can_review",
        "can_delete_drafts",
    )
    list_filter = (
        "company",
        "can_upload",
        "can_assign_dashboard_viewers",
        "can_view_own_only",
        "can_review",
        "can_delete_drafts",
    )
    search_fields = ("user__username", "user__email", "company__code")
    autocomplete_fields = ("user", "company")

    def get_cl_v2_search_placeholder(self, request):
        return _("Search username, email, or company code…")

    def get_cl_v2_stat_cards(self, request, queryset):
        return [
            cl_v2_stat_card(
                _("Total memberships"),
                queryset.count(),
                icon="bi-person-badge-fill",
            ),
            cl_v2_count_where(
                queryset,
                _("Can upload"),
                icon="bi-cloud-upload-fill",
                tone="success",
                can_upload=True,
            ),
            cl_v2_count_where(
                queryset,
                _("Can review"),
                icon="bi-clipboard-check-fill",
                tone="info",
                can_review=True,
            ),
            cl_v2_count_where(
                queryset,
                _("Can assign viewers"),
                icon="bi-people-fill",
                tone="warning",
                can_assign_dashboard_viewers=True,
            ),
        ]


CompanyMembershipAdmin.list_display = (
    "user",
    "company",
    *install_boolean_icon_list_columns(
        CompanyMembershipAdmin,
        CompanyMembership,
        CompanyMembershipAdmin._MEMBERSHIP_BOOL_FIELDS,
    ),
    "created_at",
)


@admin.register(UploadSession)
class UploadSessionAdmin(SoftDeleteAdminMixin, AdminClV2Mixin, admin.ModelAdmin):
    cl_v2_subtitle = _("Browse Excel upload sessions and imported source files.")
    list_display = ("id", "source_name", "mode", "locale", "uploaded_at")
    search_fields = ("source_name", "sheet_name", "content_sha256")
    readonly_fields = ("raw_data_json",)

    def get_cl_v2_search_placeholder(self, request):
        return _("Search file name, sheet, or hash…")

    def get_cl_v2_stat_cards(self, request, queryset):
        return [
            cl_v2_stat_card(_("Total uploads"), queryset.count(), icon="bi-upload"),
            cl_v2_count_where(
                queryset,
                _("AI mode"),
                icon="bi-robot",
                tone="success",
                mode=TEMPLATE_CODE_IAD,
            ),
            cl_v2_count_where(
                queryset,
                _("Arabic locale"),
                icon="bi-translate",
                tone="info",
                locale="ar",
            ),
            cl_v2_stat_card(
                _("With content hash"),
                queryset.exclude(content_sha256="").count(),
                icon="bi-fingerprint",
                tone="warning",
            ),
        ]


@admin.register(ObservationRecord)
class ObservationRecordAdmin(SoftDeleteAdminMixin, AdminClV2Mixin, admin.ModelAdmin):
    cl_v2_subtitle = _("Browse audit observations extracted from uploaded Excel files.")
    list_display = ("id", "upload_session", "audit_year", "company", "subcompany")
    search_fields = ("audit_year", "observation_name", "company", "subcompany")
    list_filter = ("audit_year", "company", "subcompany")

    def get_cl_v2_search_placeholder(self, request):
        return _("Search year, observation, company, or subcompany…")

    def get_cl_v2_stat_cards(self, request, queryset):
        return [
            cl_v2_stat_card(_("Total observations"), queryset.count(), icon="bi-journal-text"),
            cl_v2_stat_card(
                _("Audit years"),
                queryset.exclude(audit_year="").values("audit_year").distinct().count(),
                icon="bi-calendar3",
                tone="success",
            ),
            cl_v2_stat_card(
                _("With company"),
                queryset.exclude(company="").count(),
                icon="bi-building",
                tone="info",
            ),
            cl_v2_stat_card(
                _("Companies listed"),
                queryset.exclude(company="").values("company").distinct().count(),
                icon="bi-diagram-3-fill",
                tone="warning",
            ),
        ]


# Legacy filesystem logo table — superseded by Company.logo (kept for data migration only).
# admin.site.unregister(CompanyLogo) — not registered
@admin.register(ReportArtifact)
class ReportArtifactAdmin(SoftDeleteAdminMixin, AdminClV2Mixin, admin.ModelAdmin):
    cl_v2_subtitle = _("Browse generated report artifacts linked to upload sessions.")
    list_display = ("id", "report_id", "report_version", "rows", "columns", "created_at")
    search_fields = ("report_id", "report_version")

    def get_cl_v2_search_placeholder(self, request):
        return _("Search report ID or version…")

    def get_cl_v2_stat_cards(self, request, queryset):
        totals = queryset.aggregate(row_sum=Sum("rows"), col_sum=Sum("columns"))
        return [
            cl_v2_stat_card(_("Total artifacts"), queryset.count(), icon="bi-file-earmark-bar-graph"),
            cl_v2_stat_card(
                _("Total rows"),
                totals["row_sum"] or 0,
                icon="bi-list-ol",
                tone="success",
            ),
            cl_v2_stat_card(
                _("Total columns"),
                totals["col_sum"] or 0,
                icon="bi-layout-three-columns",
                tone="info",
            ),
            cl_v2_stat_card(
                _("Report versions"),
                queryset.values("report_version").distinct().count(),
                icon="bi-tags-fill",
                tone="warning",
            ),
        ]


@admin.register(DashboardTemplateType)
class DashboardTemplateTypeAdmin(SoftDeleteAdminMixin, AdminClV2Mixin, admin.ModelAdmin):
    soft_delete_deactivate_active_field = "is_active"
    cl_v2_subtitle = _("Manage dashboard template types shown when creating dashboards.")
    list_display = ("code", "name", "icon", "active_status_display", "sort_order")
    list_display_links = ("code",)
    search_fields = ("code", "name")
    ordering = ("sort_order", "code")
    readonly_fields = ("icon", "sort_order")
    fieldsets = (
        (None, {"fields": ("code", "name", "icon", "description")}),
        (_("Settings"), {"fields": ("is_active", "sort_order")}),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_cl_v2_search_placeholder(self, request):
        return _("Search type code or name…")

    def get_cl_v2_stat_cards(self, request, queryset):
        return [
            cl_v2_stat_card(_("Total types"), queryset.count(), icon="bi-grid-fill"),
            cl_v2_count_where(
                queryset,
                _("Active types"),
                icon="bi-check-circle-fill",
                tone="success",
                is_active=True,
            ),
            cl_v2_count_where(
                queryset,
                _("Inactive types"),
                icon="bi-pause-circle-fill",
                tone="warning",
                is_active=False,
            ),
            cl_v2_stat_card(
                _("With description"),
                queryset.exclude(description="").count(),
                icon="bi-card-text",
                tone="info",
            ),
        ]

    @admin.display(description=_("Active"), ordering="is_active")
    def active_status_display(self, obj):
        return format_admin_active_status_icon(obj.is_active)


class DashboardRejectionLogInline(admin.TabularInline):
    model = DashboardRejectionLog
    extra = 0
    readonly_fields = ("reason", "rejected_by", "created_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(DashboardRejectionLog)
class DashboardRejectionLogAdmin(SoftDeleteAdminMixin, AdminClV2Mixin, admin.ModelAdmin):
    cl_v2_subtitle = _("Review dashboard rejection history and reasons.")
    list_display = ("id", "dashboard", "rejected_by", "created_at")
    search_fields = ("reason", "dashboard__name", "rejected_by__username")
    list_filter = ("created_at",)
    readonly_fields = ("dashboard", "reason", "rejected_by", "created_at")

    def get_cl_v2_search_placeholder(self, request):
        return _("Search reason, dashboard name, or reviewer…")

    def get_cl_v2_stat_cards(self, request, queryset):
        return [
            cl_v2_stat_card(_("Total rejections"), queryset.count(), icon="bi-x-circle-fill"),
            cl_v2_stat_card(
                _("Dashboards rejected"),
                queryset.values("dashboard").distinct().count(),
                icon="bi-speedometer2",
                tone="success",
            ),
            cl_v2_stat_card(
                _("Reviewers"),
                queryset.values("rejected_by").distinct().count(),
                icon="bi-person-fill",
                tone="info",
            ),
            cl_v2_stat_card(
                _("With reason text"),
                queryset.exclude(reason="").count(),
                icon="bi-chat-left-text-fill",
                tone="warning",
            ),
        ]


@admin.register(Dashboard)
class DashboardAdmin(SoftDeleteAdminMixin, AdminClV2Mixin, ActiveCompanyFkMixin, admin.ModelAdmin):
    cl_v2_subtitle = _(
        "Browse dashboards across companies, statuses, and workflow states."
    )
    list_display = (
        "id", "name", "company", "status", "soft_deleted_display", "icon", "template_type", "created_by", "created_at",
    )
    search_fields = ("name", "report_id", "description")
    list_filter = ("company", "status", "template_type", "icon", "created_at", "created_by")
    readonly_fields = (
        "report_id", "html_file", "source_files", "created_at", "upload_session",
        "published_at", "deleted_at", "deleted_by",
    )
    inlines = [DashboardRejectionLogInline]
    fieldsets = (
        (_("Basic information"), {"fields": ("name", "description", "icon", "template_type", "company", "created_by")}),
        (_("Workflow"), {"fields": ("status", "submitted_at", "published_at", "reviewed_by")}),
        (_("Soft delete"), {"fields": ("is_deleted", "deleted_at", "deleted_by")}),
        (_("Report data"), {"fields": ("report_id", "html_file", "source_files", "upload_session")}),
        (_("Dates"), {"fields": ("created_at",)}),
    )

    def get_cl_v2_search_placeholder(self, request):
        return _("Search dashboard name, report ID, or description…")

    def get_cl_v2_stat_cards(self, request, queryset):
        in_progress = queryset.filter(status=DashboardStatus.UNDER_REVIEW).count()
        return [
            cl_v2_stat_card(_("Total dashboards"), queryset.count(), icon="bi-speedometer2"),
            cl_v2_count_where(
                queryset,
                _("Published"),
                icon="bi-check-circle-fill",
                tone="success",
                status=DashboardStatus.PUBLISHED,
            ),
            cl_v2_count_where(
                queryset,
                _("Draft"),
                icon="bi-pencil-square",
                tone="info",
                status=DashboardStatus.DRAFT,
            ),
            cl_v2_stat_card(
                _("Under review"),
                in_progress,
                icon="bi-arrow-repeat",
                tone="warning",
            ),
        ]

    @admin.display(description=_("Soft deleted"), ordering="is_deleted")
    def soft_deleted_display(self, obj):
        return format_admin_boolean_icon(
            not obj.is_deleted,
            yes_label=_("No"),
            no_label=_("Yes"),
        )

    def perform_soft_delete(self, request, obj):
        from reports_app.dashboard_workflow import soft_delete_dashboard

        soft_delete_dashboard(obj, request.user)

    def perform_restore(self, request, obj):
        from reports_app.dashboard_workflow import restore_dashboard

        restore_dashboard(obj)

    @admin.action(description=_("Restore selected dashboards"))
    def restore_dashboards(self, request, queryset):
        restored = 0
        for dashboard in queryset.filter(is_deleted=True):
            self.perform_restore(request, dashboard)
            restored += 1
        if restored:
            self.message_user(
                request,
                _("Restored %(count)d dashboard(s).") % {"count": restored},
                messages.SUCCESS,
            )

