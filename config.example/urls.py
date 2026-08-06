"""Root URL configuration wiring all Django apps."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from config.views import robots_txt, web_app_manifest

urlpatterns = [
    path("robots.txt", robots_txt, name="robots_txt"),
    path("manifest.webmanifest", web_app_manifest, name="web_app_manifest"),

    # Django built-in i18n language switcher (/i18n/set_language/)
    path("i18n/", include("django.conf.urls.i18n")),
    path("admin/", admin.site.urls),
    path("", include("accounts_app.urls")),
    path("", include("reports_app.urls")),
    path("api/", include("mail_app.urls")),
    path("api/", include("exports_app.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler404 = "reports_app.views.page_not_found_view"
