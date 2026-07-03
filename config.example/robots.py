"""Re-export site_robots for config package consumers."""

from site_robots import (
    ROBOTS_HTTP_HEADER_VALUE,
    ROBOTS_META_CONTENT,
    ROBOTS_META_HTML,
    ROBOTS_TXT,
)

__all__ = [
    "ROBOTS_HTTP_HEADER_VALUE",
    "ROBOTS_META_CONTENT",
    "ROBOTS_META_HTML",
    "ROBOTS_TXT",
]
