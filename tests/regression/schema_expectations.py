"""Schema expectations for regression tests — model fields must exist in DB."""
from __future__ import annotations

# UserProfile columns introduced or relied on by auth/admin features.
REQUIRED_USERPROFILE_COLUMNS = frozenset(
    {
        "id",
        "user_id",
        "job_title",
        "is_deleted",
        "deleted_at",
        "password_changed_at",
        "password_expiry_enabled",
        "two_factor_enabled",
        "receive_workflow_emails",
        "must_change_password_on_login",
        "preferred_language",
        "preferred_theme",
    }
)

# Django apps whose leaf migrations must be applied (no pending migrate).
REQUIRED_MIGRATION_APPS = (
    "accounts_app",
    "audit_app",
)
