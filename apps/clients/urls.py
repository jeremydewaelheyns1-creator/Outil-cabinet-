from django.urls import path

from apps.tasks import views as task_views

from . import views

app_name = "clients"

urlpatterns = [
    path("", views.client_list, name="list"),
    path("export/", views.client_export, name="export"),
    path("nouveau/", views.client_create, name="create"),
    path("choisir/", views.client_picker, name="picker"),
    path("numero-national/", views.national_number_lookup, name="nn_lookup"),
    # Dossier actif (sélecteur en haut de l'écran)
    path("dossier/recherche/", views.dossier_switcher, name="switcher"),
    path("dossier/ouvrir/<int:pk>/", views.dossier_open, name="open"),
    path("dossier/fermer/", views.dossier_close, name="close"),
    # Rubriques du dossier
    path("<int:pk>/", views.client_detail, name="detail"),
    path("<int:pk>/identite/", views.client_identity, name="identity"),
    path("<int:pk>/relations/", views.client_relations, name="relations"),
    path("<int:pk>/beneficiaires/", views.client_ubo, name="ubo"),
    path("<int:pk>/equipe/", views.client_team, name="team"),
    path("<int:pk>/bce-tva/", views.client_public_data, name="public_data"),
    path("<int:pk>/echeances/", task_views.client_tasks, name="tasks"),
    path("<int:pk>/historique/", views.client_history, name="history"),
    # Actions
    path("<int:pk>/modifier/", views.client_edit, name="edit"),
    path("<int:pk>/numero-national/", views.reveal_national_number, name="reveal_nn"),
    path("<int:pk>/equipe/modifier/", views.assignments_edit, name="assignments"),
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
