"""Singleton admin for project-wide OTP / security settings."""
from __future__ import annotations

from django import forms
from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from audit_app.admin_changelist_v2 import AdminChangeFormV2Mixin

from accounts_app.models import (
    MAX_OTP_TTL_SECONDS,
    MIN_OTP_TTL_SECONDS,
    ProjectSecuritySettings,
)
from accounts_app.services.project_timezone import project_timezone_choices


class ProjectSecuritySettingsForm(forms.ModelForm):
    otp_ttl_minutes = forms.IntegerField(
        min_value=MIN_OTP_TTL_SECONDS // 60,
        max_value=MAX_OTP_TTL_SECONDS // 60,
        label=_("OTP validity (minutes)"),
        help_text=_(
            "Email verification codes expire after this duration. "
            "Users must wait the same time before requesting a resend."
        ),
    )
    timezone = forms.ChoiceField(
        choices=project_timezone_choices,
        label=_("Project timezone"),
        help_text=_(
            "All dates and times shown in the application, admin panel, "
            "and generated reports use this timezone."
        ),
        widget=forms.Select(
            attrs={
                "class": "admin-searchable-select",
                "data-search-placeholder": _("Search timezone…"),
                "data-no-results": _("No matching timezones"),
            }
        ),
    )

    class Meta:
        model = ProjectSecuritySettings
        fields = ("otp_ttl_minutes", "timezone")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["otp_ttl_minutes"].initial = max(
                1, self.instance.otp_ttl_seconds // 60
            )

    def save(self, commit=True):
        minutes = int(self.cleaned_data["otp_ttl_minutes"])
        self.instance.otp_ttl_seconds = minutes * 60
        return super().save(commit=commit)


@admin.register(ProjectSecuritySettings)
class ProjectSecuritySettingsAdmin(AdminChangeFormV2Mixin, admin.ModelAdmin):
    form = ProjectSecuritySettingsForm
    cl_v2_page_title = _("Project security settings")
    cl_v2_subtitle = _(
        "Configure email OTP validity, project timezone, and sign-in verification "
        "behavior for all users."
    )
    fieldsets = (
        (
            _("Email OTP"),
            {
                "fields": ("otp_ttl_minutes",),
                "description": _(
                    "Controls how long sign-in verification codes remain valid. "
                    "The resend cooldown uses the same duration."
                ),
            },
        ),
        (
            _("Date and time"),
            {
                "fields": ("timezone",),
                "description": _(
                    "Sets the timezone used for all dates and times across the "
                    "dashboard, admin panel, emails, and generated reports."
                ),
            },
        ),
    )

    def has_add_permission(self, request):
        return not ProjectSecuritySettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return (
            request.user.has_perm("accounts_app.view_projectsecuritysettings")
            or self.has_change_permission(request, obj)
        )

    def has_change_permission(self, request, obj=None):
        if not request.user.is_active:
            return False
        return (
            request.user.has_perm("accounts_app.change_projectsecuritysettings")
            or request.user.has_perm("accounts_app.manage_project_timezone")
        )

    def get_readonly_fields(self, request, obj=None):
        readonly: list[str] = []
        if not request.user.has_perm("accounts_app.change_projectsecuritysettings"):
            readonly.append("otp_ttl_minutes")
        if not request.user.has_perm("accounts_app.manage_project_timezone"):
            readonly.append("timezone")
        return readonly

    def changelist_view(self, request, extra_context=None):
        settings_obj = ProjectSecuritySettings.load()
        url = reverse(
            "admin:accounts_app_projectsecuritysettings_change",
            args=[settings_obj.pk],
        )
        return HttpResponseRedirect(url)
