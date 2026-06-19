"""Fire-and-forget email tasks (workflow notifications). OTP stays synchronous."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def dispatch_in_background(target: Callable[..., None], /, *args: Any, **kwargs: Any) -> None:
    """Run *target* in a daemon thread unless EMAIL_DISPATCH_SYNC is enabled."""
    from django.conf import settings

    if getattr(settings, "EMAIL_DISPATCH_SYNC", False):
        try:
            target(*args, **kwargs)
        except Exception:
            logger.exception("Email task %s failed (sync mode)", getattr(target, "__name__", target))
        return

    def worker() -> None:
        try:
            target(*args, **kwargs)
        except Exception:
            logger.exception("Email task %s failed", getattr(target, "__name__", target))

    threading.Thread(
        target=worker,
        daemon=True,
        name=f"email-{getattr(target, '__name__', 'task')}",
    ).start()
