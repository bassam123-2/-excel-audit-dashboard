"""Django app config for audit models and company cache invalidation."""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AuditAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "audit_app"
    verbose_name = _("Excel Audit")

    def ready(self) -> None:
        from django.db.models.signals import post_delete, post_save
        from django.dispatch import receiver

        from audit_app.models import Company, CompanyAttachmentSetting

        @receiver(post_save, sender=Company)
        def ensure_company_attachment_settings(sender, instance, **kwargs):
            instance.ensure_attachment_settings()

        @receiver(post_save, sender=CompanyAttachmentSetting)
        @receiver(post_delete, sender=CompanyAttachmentSetting)
        def invalidate_dashboard_html_on_attachment_change(sender, instance, **kwargs):
            _invalidate_company_dashboard_html_cache(instance.company_id)


def _invalidate_company_dashboard_html_cache(company_id: int) -> None:
    from pathlib import Path

    from django.conf import settings

    from audit_app.models import Dashboard

    media_root = Path(settings.MEDIA_ROOT)
    dashboards_dir = media_root / "dashboards"
    for dashboard in Dashboard.objects.filter(company_id=company_id):
        if dashboards_dir.is_dir():
            for cache_file in dashboards_dir.glob(f"{dashboard.pk}_*.html"):
                try:
                    cache_file.unlink()
                except OSError:
                    pass
        if dashboard.html_file:
            html_path = media_root / dashboard.html_file
            if html_path.is_file():
                try:
                    html_path.unlink()
                except OSError:
                    pass
            Dashboard.objects.filter(pk=dashboard.pk).update(html_file="")
