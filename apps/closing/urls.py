from django.urls import path

from . import views

app_name = "closing"

urlpatterns = [
    path("", views.common_lists, name="common"),
]
