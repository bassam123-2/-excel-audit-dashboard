"""Production static file storage with content-hash cache busting.

Uses Django's built-in Manifest storage (no extra packages). Hashed filenames
(e.g. app.a1b2c3d4.js) force browsers to fetch new assets after deploy without
a hard reload. ``manifest_strict = False`` keeps pages working if a rare
template path is missing from the manifest.
"""
from __future__ import annotations

from django.contrib.staticfiles.storage import ManifestStaticFilesStorage


class ForgivingManifestStaticFilesStorage(ManifestStaticFilesStorage):
    """Manifest storage tolerant of missing manifest entries."""

    manifest_strict = False
