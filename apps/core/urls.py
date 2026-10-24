from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("journal/", views.access_log, name="access_log"),
    path("parametres/", views.settings_page, name="settings"),
    path("notifications/", views.notifications, name="notifications"),
]
