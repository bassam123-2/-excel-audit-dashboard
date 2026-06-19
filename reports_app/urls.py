"""URL routes for upload, dashboards, and /api/version."""

from django.urls import path
from django.views.generic import RedirectView

from .views import (
    analyze,
    api_version,
    dashboard_approve,
    dashboard_detail,
    dashboard_delete,
    dashboard_list,
    dashboard_reject,
    dashboard_restore,
    dashboard_serve,
    favicon,
    index,
)

urlpatterns = [
    path("", dashboard_list, name="dashboard_list"),
    path("upload/", index, name="upload"),
    path(
        "dashboards/",
        RedirectView.as_view(url="/", permanent=False),
        name="dashboard_list_legacy",
    ),
    path("analyze", analyze, name="analyze"),
    path("analyze/", analyze, name="analyze_slash"),
    path("api/version", api_version, name="api_version"),
    path("favicon.ico", favicon, name="favicon"),
    path("dashboards/<int:pk>/", dashboard_detail, name="dashboard_detail"),
    path("dashboards/<int:pk>/delete/", dashboard_delete, name="dashboard_delete"),
    path("dashboards/<int:pk>/restore/", dashboard_restore, name="dashboard_restore"),
    path("dashboards/<int:pk>/approve/", dashboard_approve, name="dashboard_approve"),
    path("dashboards/<int:pk>/reject/", dashboard_reject, name="dashboard_reject"),
    path("dashboards/<int:pk>/serve/", dashboard_serve, name="dashboard_serve"),
]
