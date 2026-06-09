from django.urls import path

from .views import login_view, logout_view, profile_view, switch_language

urlpatterns = [
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("profile/", profile_view, name="profile"),
    path("lang/switch/", switch_language, name="switch_language"),
]
