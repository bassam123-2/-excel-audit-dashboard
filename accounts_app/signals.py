"""Auto-create UserProfile when a User is created."""
from __future__ import annotations

from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import UserProfile


@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, **kwargs) -> None:
    """Create a profile row whenever a new user is created."""
    if created:
        UserProfile.objects.get_or_create(
            user=instance,
            defaults={
                "password_changed_at": timezone.now(),
                "two_factor_enabled": True,
                "password_expiry_enabled": True,
                "receive_workflow_emails": not instance.is_superuser,
            },
        )
