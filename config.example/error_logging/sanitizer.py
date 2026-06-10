"""
Redact sensitive data before it is written to log files.

Patterns cover common credential field names, HTTP auth headers, JWTs, and
key-like strings in free-form text.
"""

from __future__ import annotations

import re
from typing import Any

# Field names (case-insensitive) whose values must never appear in logs.
SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|pwd|secret|token|api[_-]?key|auth|authorization|"
    r"credential|csrf|session[_-]?key|private[_-]?key|access[_-]?key|"
    r"refresh[_-]?token|bearer|smtp[_-]?pass|db[_-]?password|"
    r"django[_-]?secret[_-]?key)",
    re.IGNORECASE,
)

# Inline patterns in messages, tracebacks, and query strings.
SENSITIVE_VALUE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9\-._~+/]+=*"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(Authorization:\s*)[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(password|passwd|pwd|secret|token|api[_-]?key)\s*[=:]\s*['\"]?[^\s'\",;]+"), r"\1=[REDACTED]"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "[REDACTED_JWT]"),
    (re.compile(r"(?i)(mysql|postgres|redis)://[^\s]+"), r"\1://[REDACTED]"),
)

REDACTED = "[REDACTED]"


def is_sensitive_key(key: str) -> bool:
    """Return True when a dict/query key should have its value redacted."""
    return bool(SENSITIVE_KEY_RE.search(str(key)))


def sanitize_text(value: str) -> str:
    """Remove or mask sensitive substrings from free-form text."""
    if not value:
        return value
    result = value
    for pattern, replacement in SENSITIVE_VALUE_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def sanitize_value(value: Any) -> Any:
    """Recursively sanitize mappings, sequences, and strings."""
    if isinstance(value, dict):
        return sanitize_mapping(value)
    if isinstance(value, (list, tuple)):
        return type(value)(sanitize_value(item) for item in value)
    if isinstance(value, str):
        return sanitize_text(value)
    return value


def sanitize_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *data* with sensitive keys and values redacted."""
    sanitized: dict[str, Any] = {}
    for key, value in data.items():
        if is_sensitive_key(key):
            sanitized[key] = REDACTED
        else:
            sanitized[key] = sanitize_value(value)
    return sanitized
