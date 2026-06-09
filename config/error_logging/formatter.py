"""
Human-readable, structured formatting for error log records.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Any

from config.error_logging.context import get_request_context
from config.error_logging.sanitizer import sanitize_mapping, sanitize_text

SEPARATOR = "=" * 80
SUB_SEPARATOR = "-" * 80


class RequestContextFilter(logging.Filter):
    """Attach active request context fields to each log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        context = get_request_context()
        record.request_id = context.get("request_id") or getattr(record, "request_id", None)
        record.user_id = context.get("user_id") if context.get("user_id") is not None else getattr(record, "user_id", None)
        record.request_path = context.get("path") or getattr(record, "request_path", None)
        record.http_method = context.get("method") or getattr(record, "http_method", None)
        record.client_ip = context.get("client_ip") or getattr(record, "client_ip", None)
        record.extra_debug_context = sanitize_mapping(
            getattr(record, "extra_debug_context", None)
            or context.get("extra_debug_context")
            or {}
        )
        return True


class StructuredErrorFormatter(logging.Formatter):
    """
    Render error records as clearly separated, developer-friendly blocks.

    Each entry includes timestamp, request metadata, exception details, stack
    trace, and optional debugging context. All text is sanitized before output.
    """

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        exc_type = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else None
        if not exc_type and record.exc_info is False and record.levelno >= logging.ERROR:
            exc_type = "LoggedError"

        message = sanitize_text(record.getMessage())
        stack_trace = self._format_stack_trace(record)

        lines = [
            SEPARATOR,
            f"ERROR RECORD | {timestamp}",
            SEPARATOR,
            f"Timestamp:      {timestamp}",
            f"Level:          {record.levelname}",
            f"Logger:         {record.name}",
            f"Request ID:     {self._display(getattr(record, 'request_id', None))}",
            f"User ID:        {self._display(getattr(record, 'user_id', None))}",
            f"HTTP Method:    {self._display(getattr(record, 'http_method', None))}",
            f"Request Path:   {self._display(getattr(record, 'request_path', None))}",
            f"Client IP:      {self._display(getattr(record, 'client_ip', None))}",
            f"Exception Type: {self._display(exc_type)}",
            f"Message:        {message}",
        ]

        if stack_trace:
            lines.extend(
                [
                    "",
                    "Stack Trace:",
                    SUB_SEPARATOR,
                    stack_trace,
                    SUB_SEPARATOR,
                ]
            )

        extra_context = getattr(record, "extra_debug_context", None) or {}
        if extra_context:
            lines.extend(["", "Additional Context:"])
            for key, value in extra_context.items():
                lines.append(f"  {key}: {sanitize_text(str(value))}")

        if record.pathname:
            lines.extend(
                [
                    "",
                    "Source:",
                    f"  {record.pathname}:{record.lineno} in {record.funcName}",
                ]
            )

        lines.append(SEPARATOR)
        return "\n".join(lines)

    def _format_stack_trace(self, record: logging.LogRecord) -> str:
        if record.exc_info:
            trace = "".join(traceback.format_exception(*record.exc_info))
            return sanitize_text(trace.rstrip())
        if record.stack_info:
            return sanitize_text(record.stack_info.rstrip())
        return ""

    @staticmethod
    def _display(value: Any) -> str:
        if value is None or value == "":
            return "—"
        return sanitize_text(str(value))
