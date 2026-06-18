"""Django admin for companies, dashboards, memberships, and users."""

from django.contrib import admin, messages
from django.contrib.admin.options import IS_POPUP_VAR, TO_FIELD_VAR
from django.contrib.admin.utils import unquote
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import PermissionDenied
from django.db.models import Q
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
        return (
            ("active", _("Active users")),
            ("deleted", _("Deleted users")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "deleted":
            return queryset.filter(profile__is_deleted=True)
        if value == "active":
            return queryset.filter(
                Q(profile__is_deleted=False) | Q(profile__isnull=True)
            )
        return queryset.filter(
            Q(profile__is_deleted=False) | Q(profile__isnull=True)
        )


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


class CompanyMembershipInline(admin.TabularInline):
    model = CompanyMembership
    extra = 1
    autocomplete_fields = ("company",)
    fk_name = "user"
    fields = (
        "company",
        "can_upload",
        "can_view",
        "can_view_own_only",
        "can_review",
        "can_delete_drafts",
    )


class ProtectedUserAdmin(BaseUserAdmin):
    """
    Blocks any modification or deletion of the default superadmin account ('myadmin').
    All other users can be managed normally by staff with user-management permissions.
    Password-based authentication is always required (no disable-password option).
    User deletion is soft — records stay in the database and can be restored.

    Dashboard upload/view/review/draft-delete are configured in Company memberships
    (inline below), not via Groups or User permissions.
    """

    PROTECTED_USERNAME = "myadmin"
    form = AdminUserChangeForm
    add_form = MandatoryPasswordAdminCreationForm
    add_form_template = "admin/auth/user/change_form.html"
    change_form_template = "admin/auth/user/change_form.html"
    inlines = [CompanyMembershipInline]
    delete_confirmation_template = "admin/auth/user/delete_confirmation.html"
    delete_selected_confirmation_template = "admin/auth/user/delete_selected_confirmation.html"
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
        "export_users_csv",
    ]
    list_filter = BaseUserAdmin.list_filter + (
        DeletedUserFilter,
        TwoFactorFilter,
        PasswordExpiryFilter,
    )

    class Media:
        css = {"all": ("css/password_rules.css",)}
        js = (
            "js/password_rules.js",
            "js/admin_email_validate.js",
            "js/admin_password_generate.js",
        )

    list_display = BaseUserAdmin.list_display + (
        "job_title_display",
        "two_factor_display",
        "password_expiry_display",
    )
    search_fields = BaseUserAdmin.search_fields + ("profile__job_title",)

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
        if obj is not None and not obj.is_superuser:
            cleaned = []
            for name, opts in fieldsets:
                fields = tuple(
                    f for f in opts.get("fields", ()) if f != "receive_workflow_emails"
                )
                cleaned.append((name, {**opts, "fields": fields}))
            fieldsets = cleaned
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
        return [
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
        ] + admin.ModelAdmin.get_urls(self)

    def generate_password_view(self, request):
        if not request.user.is_staff:
            raise PermissionDenied
        from accounts_app.services.password_generator import generate_compliant_password

        return JsonResponse({"password": generate_compliant_password()})

    def _send_credentials_email(self, request, user, raw_password: str) -> bool:
        from ai_excel_dashboard import load_smtp_config

        from accounts_app.services.credentials_email import send_credentials_email_smtp
        from accounts_app.services.email_branding import resolve_logo_url

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
            send_credentials_email_smtp(
                cfg,
                to_addr=email,
                username=user.username,
                password=raw_password,
                login_url=request.build_absolute_uri(reverse("login")),
                logo_url=resolve_logo_url(
                    base_url=request.build_absolute_uri("/"),
                    cfg=cfg,
                ),
            )
            return True
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

    def get_readonly_fields(self, request, obj=None):
        rf = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            rf += ["is_superuser", "user_permissions"]
        if not self._can_manage_user_security(request):
            rf += ["two_factor_enabled", "password_expiry_enabled"]
            if obj is None or obj.is_superuser:
                rf += ["receive_workflow_emails"]
        return rf

    def _can_manage_user_security(self, request) -> bool:
        return request.user.is_superuser or request.user.has_perm("auth.change_user")

    def _can_manage_two_factor(self, request) -> bool:
        return self._can_manage_user_security(request)

    @admin.display(description=_("2FA"), boolean=True, ordering="profile__two_factor_enabled")
    def two_factor_display(self, obj):
        profile = getattr(obj, "profile", None)
        return bool(profile and profile.two_factor_enabled)

    @admin.display(
        description=_("Pwd expiry"),
        boolean=True,
        ordering="profile__password_expiry_enabled",
    )
    def password_expiry_display(self, obj):
        profile = getattr(obj, "profile", None)
        return bool(profile and profile.password_expiry_enabled)

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

    @admin.display(description=_("Job title"), ordering="profile__job_title")
    def job_title_display(self, obj):
        profile = getattr(obj, "profile", None)
        return profile.job_title if profile and profile.job_title else "—"

    @admin.action(description=_("Restore selected users"))
    def restore_users(self, request, queryset):
        restored = 0
        for user in queryset:
            if self._is_protected(user):
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
            self.log_deletion(request, obj, str(obj))
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
        if "_restore" in request.POST and self.has_change_permission(request, obj):
            if not self._is_protected(obj):
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
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url, obj=obj
        )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, unquote(object_id))
        if obj is not None:
            extra_context["user_is_soft_deleted"] = self._is_soft_deleted(obj)
            extra_context.setdefault(
                "password_form",
                MandatoryPasswordAdminChangeForm(obj),
            )
        return super().change_view(request, object_id, form_url, extra_context)


class ProtectedGroupAdmin(BaseGroupAdmin):
    """Hide legacy dashboard permissions — use Company memberships instead."""

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
class CompanyAdmin(admin.ModelAdmin):
    form = CompanyAdminForm
    list_display = ("active_status_display", "code", "name", "company_kind", "parent", "created_at")
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
        if obj.is_active:
            return format_html(
                '<i class="bi bi-check-circle-fill company-active-status company-active-status--yes" '
                'title="{}" aria-label="{}"></i>',
                _("Active"),
                _("Active"),
            )
        return format_html(
            '<i class="bi bi-x-circle-fill company-active-status company-active-status--no" '
            'title="{}" aria-label="{}"></i>',
            _("Inactive"),
            _("Inactive"),
        )

    def get_search_results(self, request, queryset, search_term):
        """Changelist search includes inactive companies; autocomplete keeps active only."""
        if "/autocomplete/" in request.path:
            queryset = queryset.filter(is_active=True)
        return super().get_search_results(request, queryset, search_term)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["title"] = _("Companies (active and inactive)")
        return super().changelist_view(request, extra_context=extra_context)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "parent":
            from audit_app.company_access import active_main_companies

            kwargs["queryset"] = active_main_companies().order_by("code")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        form.save_attachment_settings(obj)


@admin.register(CompanyMembership)
class CompanyMembershipAdmin(ActiveCompanyFkMixin, admin.ModelAdmin):
    list_display = (
        "user",
        "company",
        "can_upload",
        "can_view",
        "can_view_own_only",
        "can_review",
        "can_delete_drafts",
        "created_at",
    )
    list_filter = (
        "company",
        "can_upload",
        "can_view",
        "can_view_own_only",
        "can_review",
        "can_delete_drafts",
    )
    search_fields = ("user__username", "user__email", "company__code")
    autocomplete_fields = ("user", "company")


@admin.register(UploadSession)
class UploadSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "source_name", "mode", "locale", "uploaded_at")
    search_fields = ("source_name", "sheet_name", "content_sha256")
    readonly_fields = ("raw_data_json",)


@admin.register(ObservationRecord)
class ObservationRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "upload_session", "audit_year", "company", "subcompany")
    search_fields = ("audit_year", "observation_name", "company", "subcompany")
    list_filter = ("audit_year", "company", "subcompany")


# Legacy filesystem logo table — superseded by Company.logo (kept for data migration only).
# admin.site.unregister(CompanyLogo) — not registered
@admin.register(ReportArtifact)
class ReportArtifactAdmin(admin.ModelAdmin):
    list_display = ("id", "report_id", "report_version", "rows", "columns", "created_at")
    search_fields = ("report_id", "report_version")


@admin.register(DashboardTemplateType)
class DashboardTemplateTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "icon", "is_active", "sort_order")
    list_editable = ("name", "is_active", "sort_order")
    list_display_links = ("code",)
    search_fields = ("code", "name")
    ordering = ("sort_order", "code")
    fieldsets = (
        (None, {"fields": ("code", "name", "icon", "description")}),
        (_("Settings"), {"fields": ("is_active", "sort_order")}),
    )


class DashboardRejectionLogInline(admin.TabularInline):
    model = DashboardRejectionLog
    extra = 0
    readonly_fields = ("reason", "rejected_by", "created_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(DashboardRejectionLog)
class DashboardRejectionLogAdmin(admin.ModelAdmin):
    list_display = ("id", "dashboard", "rejected_by", "created_at")
    search_fields = ("reason", "dashboard__name", "rejected_by__username")
    list_filter = ("created_at",)
    readonly_fields = ("dashboard", "reason", "rejected_by", "created_at")


@admin.register(Dashboard)
class DashboardAdmin(ActiveCompanyFkMixin, admin.ModelAdmin):
    list_display = (
        "id", "name", "company", "status", "is_deleted", "icon", "template_type", "created_by", "created_at",
    )
    search_fields = ("name", "report_id", "description")
    list_filter = ("company", "is_deleted", "status", "template_type", "icon", "created_at", "created_by")
    readonly_fields = (
        "report_id", "html_file", "source_files", "created_at", "upload_session",
        "published_at", "deleted_at", "deleted_by",
    )
    inlines = [DashboardRejectionLogInline]
    actions = ["restore_dashboards"]
    fieldsets = (
        (_("Basic information"), {"fields": ("name", "description", "icon", "template_type", "company", "created_by")}),
        (_("Workflow"), {"fields": ("status", "published_at", "reviewed_by")}),
        (_("Soft delete"), {"fields": ("is_deleted", "deleted_at", "deleted_by")}),
        (_("Report data"), {"fields": ("report_id", "html_file", "source_files", "upload_session")}),
        (_("Dates"), {"fields": ("created_at",)}),
    )

    @admin.action(description=_("Restore selected dashboards"))
    def restore_dashboards(self, request, queryset):
        from reports_app.dashboard_workflow import restore_dashboard

        count = 0
        for dashboard in queryset.filter(is_deleted=True):
            restore_dashboard(dashboard)
            count += 1
        self.message_user(request, _("Restored %(count)d dashboard(s).") % {"count": count})
