"""UserProfile and password-expiry settings linked to Django User."""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

PASSWORD_MAX_AGE_DAYS = 180


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
        default=False,
        verbose_name=_("Email two-factor authentication"),
        help_text=_(
            "When enabled, a one-time code is sent by email at sign-in. "
            "Disabled by default — enable per user or for all users from the admin."
        ),
    )
    receive_workflow_emails = models.BooleanField(
        default=False,
        verbose_name=_("Receive workflow notification emails"),
        help_text=_(
            "Superuser accounts only. When enabled, this support account receives "
            "dashboard pending-review, publish, and related workflow emails."
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

    class Meta:
        verbose_name = _("User profile")
        verbose_name_plural = _("User profiles")

    def __str__(self) -> str:
        return f"{self.user.username} — {self.job_title or _('No job title')}"
