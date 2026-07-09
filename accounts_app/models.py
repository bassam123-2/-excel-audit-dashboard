"""UserProfile and password-expiry settings linked to Django User."""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

PASSWORD_MAX_AGE_DAYS = 180

DEFAULT_OTP_TTL_SECONDS = 600
MIN_OTP_TTL_SECONDS = 60
MAX_OTP_TTL_SECONDS = 3600
DEFAULT_PROJECT_TIMEZONE = "UTC"


class ProjectSecuritySettings(models.Model):
    """Project-wide security settings (singleton row, pk=1)."""

    otp_ttl_seconds = models.PositiveIntegerField(
        default=DEFAULT_OTP_TTL_SECONDS,
        verbose_name=_("OTP validity (seconds)"),
        help_text=_(
            "How long email verification codes remain valid. "
            "The resend cooldown uses the same duration. "
            f"Allowed range: {MIN_OTP_TTL_SECONDS}–{MAX_OTP_TTL_SECONDS} seconds."
        ),
    )
    timezone = models.CharField(
        max_length=63,
        default=DEFAULT_PROJECT_TIMEZONE,
        verbose_name=_("Project timezone"),
        help_text=_(
            "All dates and times shown in the application, admin panel, "
            "and generated reports use this timezone."
        ),
    )

    class Meta:
        verbose_name = _("Project security settings")
        verbose_name_plural = _("Project security settings")
        permissions = [
            (
                "manage_project_timezone",
                _("Can change project timezone"),
            ),
        ]

    def __str__(self) -> str:
        minutes = max(1, self.otp_ttl_seconds // 60)
        return _("OTP validity: {minutes} min").format(minutes=minutes)

    def save(self, *args, **kwargs) -> None:
        self.pk = 1
        super().save(*args, **kwargs)
        from accounts_app.services.otp_settings import invalidate_otp_settings_cache
        from accounts_app.services.project_timezone import invalidate_project_timezone_cache

        invalidate_otp_settings_cache()
        invalidate_project_timezone_cache()

    @classmethod
    def load(cls) -> ProjectSecuritySettings:
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "otp_ttl_seconds": DEFAULT_OTP_TTL_SECONDS,
                "timezone": DEFAULT_PROJECT_TIMEZONE,
            },
        )
        return obj


class UserProfile(models.Model):
    """Extended profile fields for Django auth users."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name=_("User"),
    )
    job_title = models.CharField(
        max_length=128,
        blank=False,
        verbose_name=_("Job title"),
        help_text=_("The user's job title or position."),
    )
    is_deleted = models.BooleanField(
        default=False,
        verbose_name=_("Deleted"),
        help_text=_("Soft-deleted users remain in the database but cannot sign in."),
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Deleted at"),
    )
    password_changed_at = models.DateTimeField(
        default=timezone.now,
        verbose_name=_("Password last changed"),
    )
    password_expiry_enabled = models.BooleanField(
        default=True,
        verbose_name=_("Require password change every 6 months"),
        help_text=_(
            "When enabled, the user must change their password "
            f"every {PASSWORD_MAX_AGE_DAYS} days."
        ),
    )
    two_factor_enabled = models.BooleanField(
        default=True,
        verbose_name=_("Email two-factor authentication"),
        help_text=_(
            "When enabled, a one-time code is sent by email at sign-in. "
            "Enabled by default for new users — disable per user from the admin if needed."
        ),
    )
    receive_workflow_emails = models.BooleanField(
        default=False,
        verbose_name=_("Receive workflow notification emails"),
        help_text=_(
            "When enabled, the user receives dashboard workflow emails "
            "(pending review, publish, rejection, assignment). "
            "Superuser accounts are opt-in; other users are enabled by default."
        ),
    )
    must_change_password_on_login = models.BooleanField(
        default=False,
        verbose_name=_("Must change password on next sign-in"),
        help_text=_(
            "When enabled, the user is redirected to change their password "
            "before accessing the application."
        ),
    )
    preferred_language = models.CharField(
        max_length=2,
        choices=(("en", _("English")), ("ar", _("Arabic"))),
        default="en",
        verbose_name=_("Preferred language"),
        help_text=_("UI language for the dashboard and administration site."),
    )
    preferred_theme = models.CharField(
        max_length=5,
        choices=(("light", _("Light")), ("dark", _("Dark"))),
        default="light",
        verbose_name=_("Preferred theme"),
        help_text=_("Light or dark appearance for the dashboard and admin site."),
    )

    def is_password_expired(self) -> bool:
        if not self.password_expiry_enabled:
            return False
        if not self.password_changed_at:
            return True
        age = timezone.now() - self.password_changed_at
        return age > timedelta(days=PASSWORD_MAX_AGE_DAYS)

    @classmethod
    def bulk_set_password_expiry(
        cls,
        *,
        enabled: bool,
        users=None,
    ) -> int:
        """Enable or disable 6-month password expiry; creates missing profiles."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user_qs = users if users is not None else User.objects.all()
        updated = 0
        for user in user_qs.iterator():
            profile, _ = cls.objects.get_or_create(user=user)
            if profile.password_expiry_enabled != enabled:
                profile.password_expiry_enabled = enabled
                profile.save(update_fields=["password_expiry_enabled"])
                updated += 1
        return updated

    @classmethod
    def bulk_set_two_factor(
        cls,
        *,
        enabled: bool,
        users=None,
    ) -> int:
        """Enable or disable 2FA on profiles; creates missing profiles."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user_qs = users if users is not None else User.objects.all()
        updated = 0
        for user in user_qs.iterator():
            profile, _ = cls.objects.get_or_create(user=user)
            if profile.two_factor_enabled != enabled:
                profile.two_factor_enabled = enabled
                profile.save(update_fields=["two_factor_enabled"])
                updated += 1
        return updated

    @classmethod
    def bulk_set_receive_workflow_emails(
        cls,
        *,
        enabled: bool,
        users=None,
    ) -> int:
        """Enable or disable workflow notification emails; creates missing profiles."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user_qs = users if users is not None else User.objects.all()
        updated = 0
        for user in user_qs.iterator():
            profile, _ = cls.objects.get_or_create(user=user)
            if profile.receive_workflow_emails != enabled:
                profile.receive_workflow_emails = enabled
                profile.save(update_fields=["receive_workflow_emails"])
                updated += 1
        return updated

    class Meta:
        verbose_name = _("User profile")
        verbose_name_plural = _("User profiles")

    def __str__(self) -> str:
        return f"{self.user.username} — {self.job_title or _('No job title')}"


PASSWORD_SET_TOKEN_TTL_HOURS = 72


class PasswordSetToken(models.Model):
    """One-time link for new/reset users to set their password without email plaintext."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="password_set_tokens",
        verbose_name=_("User"),
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Password set token")
        verbose_name_plural = _("Password set tokens")
        indexes = [
            models.Index(fields=["user", "used_at"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:
        status = _("used") if self.used_at else _("active")
        return f"{self.user.username} — {status}"

    @property
    def is_valid(self) -> bool:
        if self.used_at is not None:
            return False
        return timezone.now() < self.expires_at
