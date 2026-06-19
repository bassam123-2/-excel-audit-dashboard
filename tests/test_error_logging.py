"""Tests for centralized error logging utilities."""

from __future__ import annotations

import logging

import pytest

from config.error_logging.formatter import StructuredErrorFormatter
from config.error_logging.sanitizer import REDACTED, sanitize_mapping, sanitize_text
from config.error_logging.setup import (
    ERROR_LOG_BACKUP_COUNT,
    ERROR_LOG_MAX_BYTES,
    build_logging_config,
)


class TestSanitizer:
    def test_redacts_sensitive_keys(self):
        data = {"username": "alice", "password": "s3cret", "api_key": "abc123"}
        result = sanitize_mapping(data)
        assert result["username"] == "alice"
        assert result["password"] == REDACTED
        assert result["api_key"] == REDACTED

    def test_redacts_bearer_tokens_in_text(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def"
        result = sanitize_text(text)
        assert "eyJhbGci" not in result
        assert REDACTED in result or "[REDACTED" in result

    def test_redacts_password_query_params(self):
        text = "login?password=hidden&user=admin"
        result = sanitize_text(text)
        assert "hidden" not in result


class TestLoggingSetup:
    def test_rotation_limits(self):
        assert ERROR_LOG_MAX_BYTES == 50 * 1024 * 1024
        assert ERROR_LOG_BACKUP_COUNT == 2

    def test_disabled_config_uses_null_handler(self, tmp_path):
        config = build_logging_config(tmp_path, enabled=False)
        assert config["loggers"]["app.errors"]["handlers"] == ["null"]


class TestStructuredFormatter:
    def test_formats_human_readable_block(self):
        formatter = StructuredErrorFormatter()
        record = logging.LogRecord(
            name="app.errors",
            level=logging.ERROR,
            pathname=__file__,
            lineno=10,
            msg="Something failed",
            args=(),
            exc_info=None,
        )
        record.request_id = "req-123"
        record.user_id = 7
        record.http_method = "POST"
        record.request_path = "/api/upload/"
        record.client_ip = "127.0.0.1"
        record.extra_debug_context = {"dashboard_id": 42}

        output = formatter.format(record)
        assert "ERROR RECORD" in output
        assert "req-123" in output
        assert "POST" in output
        assert "/api/upload/" in output
        assert "dashboard_id: 42" in output
