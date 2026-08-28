"""ASGI entry point for async servers."""

from django.core.asgi import get_asgi_application

from django_boot import apply_env

apply_env(default="config.settings.development")

application = get_asgi_application()
