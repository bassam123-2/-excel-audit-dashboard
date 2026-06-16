"""Test data factories."""
from __future__ import annotations

from django.contrib.auth.models import User

from audit_app.models import Company, CompanyMembership, Dashboard, DashboardStatus


def make_user(username: str, *, email: str = "", password: str = "Test@1234") -> User:
    user = User.objects.create_user(
        username,
        password=password,
        email=email or f"{username}@example.com",
        first_name="Test",
        last_name="User",
    )
    profile = user.profile
    profile.two_factor_enabled = False
    profile.job_title = profile.job_title or "Tester"
    profile.save(update_fields=["two_factor_enabled", "job_title"])
    return user


def make_membership(
    user: User,
    company: Company,
    *,
    can_upload: bool = False,
    can_view: bool = False,
    can_view_own_only: bool = False,
    can_review: bool = False,
    can_delete_drafts: bool = False,
) -> CompanyMembership:
    return CompanyMembership.objects.create(
        user=user,
        company=company,
        can_upload=can_upload,
        can_view=can_view,
        can_view_own_only=can_view_own_only,
        can_review=can_review,
        can_delete_drafts=can_delete_drafts,
    )


def make_dashboard(
    company: Company,
    creator: User,
    *,
    name: str = "Test Dash",
    status: str = DashboardStatus.PUBLISHED,
) -> Dashboard:
    return Dashboard.objects.create(
        name=name,
        report_id=f"rid-{name}-{company.code}",
        company=company,
        created_by=creator,
        status=status,
    )
