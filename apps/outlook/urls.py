from django.urls import path

from . import views

app_name = "outlook"

urlpatterns = [
    path("", views.mailbox, name="mailbox"),
    path("relier/", views.connect, name="connect"),
    path("retour/", views.callback, name="callback"),
    path("delier/", views.disconnect, name="disconnect"),
]
