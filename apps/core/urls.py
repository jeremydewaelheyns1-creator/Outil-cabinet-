from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("ma-journee/", views.today_view, name="today"),
    path("parametres/cabinet/", views.cabinet_settings, name="cabinet_settings"),
    path("journal/", views.access_log, name="access_log"),
    path("parametres/", views.settings_page, name="settings"),
    path("notifications/", views.notifications, name="notifications"),
    path("ma-journee/agenda/", views.my_agenda, name="agenda"),
    path("ma-journee/agenda/echeance/", views.agenda_deadline, name="agenda_deadline"),
]
