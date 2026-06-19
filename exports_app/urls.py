"""URL routes under /api/exports/."""

from django.urls import path

from .views import health

urlpatterns = [
    path("exports/health", health, name="exports_health"),
    path("exports/health/", health, name="exports_health_slash"),
]
