"""Django app config for accounts (auth extensions)."""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AccountsAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts_app"
    verbose_name = _("Authentication & Accounts")

    def ready(self) -> None:
        from . import signals  # noqa: F401
