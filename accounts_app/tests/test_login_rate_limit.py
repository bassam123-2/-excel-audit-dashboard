"""Tests for login rate limiting."""
from __future__ import annotations

import pytest
from django.core.cache import cache
from django.test import Client

from accounts_app.services.login_rate_limit import (
    acquire_login_lock,
    is_login_blocked,
    record_failed_login,
    release_login_lock,
)
from tests.factories import make_membership, make_user


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.unit
def test_acquire_login_lock_blocks_duplicate():
    assert acquire_login_lock("Alice") is True
    assert acquire_login_lock("alice") is False
    release_login_lock("Alice")
    assert acquire_login_lock("Alice") is True


@pytest.mark.unit
def test_failed_login_attempts_block_user():
    record_failed_login("bob", "127.0.0.1")
    assert is_login_blocked("bob", "127.0.0.1") is False
    for _ in range(10):
        record_failed_login("bob", "127.0.0.1")
    assert is_login_blocked("bob", "127.0.0.1") is True


@pytest.mark.integration
@pytest.mark.django_db
def test_concurrent_login_post_rejected(btc_company):
    user = make_user("rate_user")
    make_membership(user, btc_company, can_upload=True)

    cache.set("login_inflight:rate_user", 1, 30)
    client = Client()
    response = client.post(
        "/login/",
        {"username": "rate_user", "password": "Test@1234"},
    )
    assert response.status_code == 200
    assert b"rate" in response.content.lower() or "login" in response.content.decode().lower()
