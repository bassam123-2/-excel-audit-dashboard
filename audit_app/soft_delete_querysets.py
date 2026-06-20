"""Shared queryset helpers for admin soft-delete visibility rules."""
from __future__ import annotations

from django.db.models import Q, QuerySet


def exclude_soft_deleted(queryset: QuerySet) -> QuerySet:
    if hasattr(queryset.model, "is_deleted"):
        return queryset.filter(is_deleted=False)
    return queryset


def exclude_soft_deleted_users(queryset: QuerySet) -> QuerySet:
    return queryset.filter(Q(profile__is_deleted=False) | Q(profile__isnull=True))
