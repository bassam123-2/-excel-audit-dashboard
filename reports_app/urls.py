from django.urls import path

from .views import analyze, api_version, index

urlpatterns = [
    path("", index, name="index"),
    path("analyze", analyze, name="analyze"),
    path("analyze/", analyze, name="analyze_slash"),
    path("api/version", api_version, name="api_version"),
]
