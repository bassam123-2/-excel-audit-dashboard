from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings


def test_check_static_manifest_rejects_unhashed_storage():
    with override_settings(
        DEBUG=False,
        STORAGES={
            "default": {
                "BACKEND": "django.core.files.storage.FileSystemStorage",
            },
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
            },
        },
    ):
        with pytest.raises(CommandError, match="Manifest"):
            call_command("check_static_manifest")


def test_check_static_manifest_rejects_debug():
    with override_settings(
        DEBUG=True,
        STORAGES={
            "default": {
                "BACKEND": "django.core.files.storage.FileSystemStorage",
            },
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
            },
        },
    ):
        with pytest.raises(CommandError, match="DEBUG"):
            call_command("check_static_manifest")


def test_check_static_manifest_accepts_manifest_backend():
    with override_settings(
        DEBUG=False,
        STORAGES={
            "default": {
                "BACKEND": "django.core.files.storage.FileSystemStorage",
            },
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
            },
        },
    ):
        call_command("check_static_manifest")
