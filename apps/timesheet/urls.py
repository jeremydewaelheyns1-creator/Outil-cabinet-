from django.urls import path

from . import views

app_name = "temps"

urlpatterns = [
    path("", views.week, name="week"),
    path("enregistrer/", views.save, name="save"),
    path("<int:entry_id>/supprimer/", views.delete, name="delete"),
]
