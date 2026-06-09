from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AuditAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "audit_app"
    verbose_name = _("Excel Audit")

    def ready(self) -> None:
        from django.contrib.auth.models import User

        is_staff = User._meta.get_field("is_staff")
        is_staff.verbose_name = _("Admin")
        is_staff.help_text = _(
            "Designates whether this user has admin access to the administration site."
        )
