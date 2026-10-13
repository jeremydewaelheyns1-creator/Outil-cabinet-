from django.urls import path

from . import views

app_name = "clients"

urlpatterns = [
    path("", views.client_list, name="list"),
    path("export/", views.client_export, name="export"),
    path("nouveau/", views.client_create, name="create"),
    path("choisir/", views.client_picker, name="picker"),
    path("<int:pk>/", views.client_detail, name="detail"),
    path("<int:pk>/modifier/", views.client_edit, name="edit"),
    path("<int:pk>/numero-national/", views.reveal_national_number, name="reveal_nn"),
    path("<int:pk>/historique/", views.client_history, name="history"),
    path("<int:pk>/equipe/", views.assignments_edit, name="assignments"),
    path("<int:pk>/coordonnees/ajouter/", views.contact_add, name="contact_add"),
    path(
        "<int:pk>/coordonnees/<int:contact_pk>/supprimer/",
        views.contact_delete,
        name="contact_delete",
    ),
    path("<int:pk>/relations/ajouter/", views.relation_edit, name="relation_add"),
    path(
        "<int:pk>/relations/<int:relation_pk>/modifier/",
        views.relation_edit,
        name="relation_edit",
    ),
    path(
        "<int:pk>/relations/<int:relation_pk>/supprimer/",
        views.relation_delete,
        name="relation_delete",
    ),
    path("<int:pk>/bce/appliquer/", views.bce_apply, name="bce_apply"),
    path("<int:pk>/bce/actualiser/", views.bce_refresh, name="bce_refresh"),
    path("<int:pk>/vies/", views.vies_check, name="vies_check"),
]
