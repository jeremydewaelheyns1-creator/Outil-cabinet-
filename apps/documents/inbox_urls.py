from django.urls import path

from . import inbox_views

app_name = "depot"

urlpatterns = [
    path("", inbox_views.index, name="index"),
    path("<uuid:item_id>/fichier/", inbox_views.item_file, name="file"),
    path("<uuid:item_id>/classer/", inbox_views.item_classify, name="classify"),
    path("<uuid:item_id>/supprimer/", inbox_views.item_delete, name="delete"),
]
