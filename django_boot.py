"""Load ``.env`` before Django chooses a settings module.

``manage.py`` used to ``setdefault`` development settings first. python-dotenv
does not override existing variables, so ``DJANGO_SETTINGS_MODULE`` from ``.env``
was ignored. VPS ``collectstatic`` then ran with unhashed ``StaticFilesStorage``
while gunicorn served Manifest URLs — CSS/JS deploys looked like a no-op.

Also strips accidental extra tokens such as a gunicorn command appended on the
same ``DJANGO_SETTINGS_MODULE=`` line.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_SETTINGS_MODULE_RE = re.compile(r"^[\w.]+$")


def sanitize_django_settings_module(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = str(raw).replace("\r", "").strip().strip("\"'")
    if not value:
        return None
    token = value.split()[0]
    if not _SETTINGS_MODULE_RE.match(token):
        return None
    return token


def apply_env(*, default: str, env_file: Path | None = None) -> str:
    """Load ``.env``, sanitize settings module, then setdefault ``default``."""
    root = Path(__file__).resolve().parent
    path = env_file if env_file is not None else root / ".env"
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None
    if load_dotenv is not None and path.is_file():
        load_dotenv(path)

    current = os.environ.get("DJANGO_SETTINGS_MODULE")
    sanitized = sanitize_django_settings_module(current)
    if sanitized:
        os.environ["DJANGO_SETTINGS_MODULE"] = sanitized
    elif "DJANGO_SETTINGS_MODULE" in os.environ:
        del os.environ["DJANGO_SETTINGS_MODULE"]

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", default)
    return os.environ["DJANGO_SETTINGS_MODULE"]
