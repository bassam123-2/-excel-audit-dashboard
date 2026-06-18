"""Singleton admin for project-wide OTP / security settings."""
from __future__ import annotations

from django import forms
from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from accounts_app.models import (
    MAX_OTP_TTL_SECONDS,
    MIN_OTP_TTL_SECONDS,
    ProjectSecuritySettings,
)


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

    class Meta:
        model = ProjectSecuritySettings
        fields = ("otp_ttl_minutes",)

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
class ProjectSecuritySettingsAdmin(admin.ModelAdmin):
    form = ProjectSecuritySettingsForm
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
    )

    def has_add_permission(self, request):
        return not ProjectSecuritySettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        settings_obj = ProjectSecuritySettings.load()
        url = reverse(
            "admin:accounts_app_projectsecuritysettings_change",
            args=[settings_obj.pk],
        )
        return HttpResponseRedirect(url)
