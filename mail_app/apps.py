"""Django app config for mail and PPTX parse APIs."""

from django.apps import AppConfig


class MailAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mail_app"
