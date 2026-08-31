"""WSGI entry point for production servers."""

from django.core.wsgi import get_wsgi_application

from django_boot import apply_env

apply_env(default="config.settings.production")

application = get_wsgi_application()
