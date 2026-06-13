from __future__ import annotations

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
        blank=True,
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
    two_factor_enabled = models.BooleanField(
        default=False,
        verbose_name=_("Email two-factor authentication"),
        help_text=_(
            "When enabled, a one-time code is sent by email at sign-in. "
            "Disabled by default — enable per user or for all users from the admin."
        ),
    )

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
