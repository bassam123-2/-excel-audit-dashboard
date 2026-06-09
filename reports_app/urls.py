from django.urls import path

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
    path("", index, name="index"),
    path("analyze", analyze, name="analyze"),
    path("analyze/", analyze, name="analyze_slash"),
    path("api/version", api_version, name="api_version"),
    path("favicon.ico", favicon, name="favicon"),
    path("dashboards/", dashboard_list, name="dashboard_list"),
    path("dashboards/<int:pk>/", dashboard_detail, name="dashboard_detail"),
    path("dashboards/<int:pk>/delete/", dashboard_delete, name="dashboard_delete"),
    path("dashboards/<int:pk>/restore/", dashboard_restore, name="dashboard_restore"),
    path("dashboards/<int:pk>/approve/", dashboard_approve, name="dashboard_approve"),
    path("dashboards/<int:pk>/reject/", dashboard_reject, name="dashboard_reject"),
    path("dashboards/<int:pk>/serve/", dashboard_serve, name="dashboard_serve"),
]
