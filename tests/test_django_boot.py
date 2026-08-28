from __future__ import annotations

from django_boot import apply_env, sanitize_django_settings_module


def test_sanitize_strips_gunicorn_command():
    assert (
        sanitize_django_settings_module(
            "config.settings.production gunicorn --bind 0.0.0.0:8000"
        )
        == "config.settings.production"
    )


def test_sanitize_rejects_empty():
    assert sanitize_django_settings_module("   ") is None
    assert sanitize_django_settings_module(None) is None


def test_apply_env_reads_dotenv_before_default(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DJANGO_SETTINGS_MODULE=config.settings.production\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    applied = apply_env(
        default="config.settings.development",
        env_file=env_file,
    )
    assert applied == "config.settings.production"


def test_apply_env_does_not_override_existing_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DJANGO_SETTINGS_MODULE=config.settings.production\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings.test")
    applied = apply_env(
        default="config.settings.development",
        env_file=env_file,
    )
    assert applied == "config.settings.test"


def test_apply_env_sanitizes_existing_garbage(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "DJANGO_SETTINGS_MODULE",
        "config.settings.production gunicorn --bind 127.0.0.1:8000",
    )
    applied = apply_env(
        default="config.settings.development",
        env_file=tmp_path / "missing.env",
    )
    assert applied == "config.settings.production"
