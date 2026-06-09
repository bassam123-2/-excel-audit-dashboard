from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.contrib.auth import update_session_auth_hash
from django.contrib.admin.options import IS_POPUP_VAR
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.html import escape
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.views.decorators.debug import sensitive_post_parameters

from .admin_forms import (
    AdminUserChangeForm,
    MandatoryPasswordAdminChangeForm,
    MandatoryPasswordAdminCreationForm,
)

from .models import (
    CompanyLogo, Dashboard, DashboardReview, DashboardTemplateType,
    ObservationRecord, ReportArtifact, UploadSession,
)

# ── Protected User Admin ─────────────────────────────────────────────


class ProtectedUserAdmin(BaseUserAdmin):
    """
    Blocks any modification or deletion of the default superadmin account ('myadmin').
    All other users can be managed normally by staff with user-management permissions.
    Password-based authentication is always required (no disable-password option).
    """

    PROTECTED_USERNAME = "myadmin"
    form = AdminUserChangeForm
    add_form = MandatoryPasswordAdminCreationForm
    change_password_form = MandatoryPasswordAdminChangeForm
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2"),
            },
        ),
    )

    def _is_protected(self, obj) -> bool:
        return obj is not None and (
            obj.username == self.PROTECTED_USERNAME or obj.is_superuser
        )

    def has_change_permission(self, request, obj=None):
        if self._is_protected(obj) and not request.user.username == self.PROTECTED_USERNAME:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self._is_protected(obj):
            return False
        return super().has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        rf = list(super().get_readonly_fields(request, obj))
        # Prevent non-superadmins from granting is_superuser flag
        if not request.user.is_superuser:
            rf += ["is_superuser", "user_permissions"]
        return rf

    @method_decorator(sensitive_post_parameters())
    def user_change_password(self, request, id, form_url=""):
        user = self.get_object(request, unquote(id))
        if not self.has_change_permission(request, user):
            raise PermissionDenied
        if user is None:
            raise Http404(
                _("%(name)s object with primary key %(key)r does not exist.")
                % {
                    "name": self.opts.verbose_name,
                    "key": escape(id),
                }
            )
        if request.method == "POST":
            form = self.change_password_form(user, request.POST)
            if form.is_valid():
                user = form.save()
                change_message = self.construct_change_message(request, form, None)
                self.log_change(request, user, change_message)
                messages.success(request, gettext("Password changed successfully."))
                update_session_auth_hash(request, form.user)
                return HttpResponseRedirect(
                    reverse(
                        "%s:%s_%s_change"
                        % (
                            self.admin_site.name,
                            user._meta.app_label,
                            user._meta.model_name,
                        ),
                        args=(user.pk,),
                    )
                )
        else:
            form = self.change_password_form(user)

        fieldsets = [(None, {"fields": list(form.base_fields)})]
        admin_form = admin.helpers.AdminForm(form, fieldsets, {})
        context = {
            "title": _("Change password: %s") % escape(user.get_username()),
            "adminForm": admin_form,
            "form_url": form_url,
            "form": form,
            "is_popup": (IS_POPUP_VAR in request.POST or IS_POPUP_VAR in request.GET),
            "is_popup_var": IS_POPUP_VAR,
            "add": True,
            "change": False,
            "has_delete_permission": False,
            "has_change_permission": True,
            "has_absolute_url": False,
            "opts": self.opts,
            "original": user,
            "save_as": False,
            "show_save": True,
            **self.admin_site.each_context(request),
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(
            request,
            self.change_user_password_template
            or "admin/auth/user/change_password.html",
            context,
        )


admin.site.unregister(User)
admin.site.register(User, ProtectedUserAdmin)


# ── App models ───────────────────────────────────────────────────────


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


@admin.register(CompanyLogo)
class CompanyLogoAdmin(admin.ModelAdmin):
    list_display = ("id", "company_key", "subcompany_key", "asset_path")
    search_fields = ("company_key", "subcompany_key")


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


@admin.register(DashboardReview)
class DashboardReviewAdmin(admin.ModelAdmin):
    list_display = ("id", "dashboard", "author", "created_at")
    search_fields = ("body", "author__username", "dashboard__name")
    list_filter = ("created_at",)
    readonly_fields = ("created_at",)


@admin.register(Dashboard)
class DashboardAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "icon", "template_type", "created_by", "created_at")
    search_fields = ("name", "report_id", "description")
    list_filter = ("template_type", "icon", "created_at", "created_by")
    readonly_fields = ("report_id", "html_file", "source_files", "created_at", "upload_session")
    fieldsets = (
        (_("Basic information"), {"fields": ("name", "description", "icon", "template_type", "created_by")}),
        (_("Report data"), {"fields": ("report_id", "html_file", "source_files", "upload_session")}),
        (_("Dates"), {"fields": ("created_at",)}),
    )
