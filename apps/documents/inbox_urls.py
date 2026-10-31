from django.urls import path

from . import inbox_views

app_name = "depot"

urlpatterns = [
    path("", inbox_views.index, name="index"),
    path("<uuid:item_id>/fichier/", inbox_views.item_file, name="file"),
    path("<uuid:item_id>/classer/", inbox_views.item_classify, name="classify"),
    path("<uuid:item_id>/supprimer/", inbox_views.item_delete, name="delete"),
    path("<uuid:item_id>/assistant/", inbox_views.item_assist, name="assist"),
    path("<uuid:item_id>/page/<int:number>/", inbox_views.item_page, name="page"),
    path("<uuid:item_id>/doublon/", inbox_views.duplicate, name="duplicate"),
    path(
        "<uuid:item_id>/doublon/importer/", inbox_views.duplicate_confirm, name="duplicate_confirm"
    ),
    path(
        "<uuid:item_id>/doublon/supprimer/", inbox_views.duplicate_delete, name="duplicate_delete"
    ),
]
