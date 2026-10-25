from django.urls import path

from apps.documents import risk_views
from apps.documents import views as document_views
from apps.tasks import views as task_views
from apps.timesheet import views as timesheet_views
from apps.vat import views as vat_views

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
    path("<int:pk>/mandataires/", views.client_mandates, name="mandates"),
    path("<int:pk>/actionnaires/", views.client_shareholders, name="shareholders"),
    path("<int:pk>/documents/beneficiaires-effectifs/", views.client_ubo, name="ubo"),
    path("<int:pk>/comptes-annuels/", views.client_annual_accounts, name="annual_accounts"),
    path("<int:pk>/echeances/", task_views.client_tasks, name="tasks"),
    path("<int:pk>/historique/", views.client_history, name="history"),
    path("<int:pk>/temps-passe/", timesheet_views.client_time, name="time_spent"),
    path("<int:pk>/travail/<slug:slug>/", views.client_work, name="work"),
    # Déclaration TVA (D-040)
    path("<int:pk>/tva/", vat_views.vat_grid, name="vat"),
    path("<int:pk>/tva/<int:filing_id>/case/<slug:column>/", vat_views.vat_cell, name="vat_cell"),
    path("<int:pk>/tva/<int:filing_id>/montants/", vat_views.vat_amounts, name="vat_amounts"),
    path("<int:pk>/tva/<int:filing_id>/email/", vat_views.vat_mail, name="vat_mail"),
    path("<int:pk>/tva/a-confirmer/<int:pending_id>/", vat_views.vat_confirm, name="vat_confirm"),
    path("<int:pk>/archives/<slug:slug>/", views.client_archive, name="archive"),
    path("<int:pk>/documents/", views.client_documents, name="documents"),
    path("<int:pk>/documents/ajouter/", document_views.upload, name="document_upload"),
    path(
        "<int:pk>/documents/fichier/<uuid:document_id>/",
        document_views.document_file,
        name="document_file",
    ),
    path(
        "<int:pk>/documents/apercu/<uuid:document_id>/",
        document_views.document_viewer_page,
        name="document_viewer_page",
    ),
    path(
        "<int:pk>/documents/apercu/<uuid:document_id>/fenetre/",
        document_views.document_viewer,
        name="document_viewer",
    ),
    path(
        "<int:pk>/documents/apercu/<uuid:document_id>/page-<int:number>.png",
        document_views.document_page,
        name="document_page",
    ),
    path(
        "<int:pk>/documents/generer/<slug:doc_type>/",
        document_views.document_generate,
        name="document_generate",
    ),
    path(
        "<int:pk>/documents/brouillon/<uuid:document_id>/valider/",
        document_views.document_finalize,
        name="document_finalize",
    ),
    path(
        "<int:pk>/documents/brouillon/<uuid:document_id>/envoyer/",
        document_views.document_send,
        name="document_send",
    ),
    path(
        "<int:pk>/documents/brouillon/<uuid:document_id>/supprimer/",
        document_views.document_discard,
        name="document_discard",
    ),
    path("<int:pk>/documents/demander/", document_views.request_create, name="request_create"),
    path(
        "<int:pk>/documents/demande/<uuid:request_id>/recue/",
        document_views.request_receive,
        name="request_receive",
    ),
    path(
        "<int:pk>/documents/demande/<uuid:request_id>/annuler/",
        document_views.request_cancel,
        name="request_cancel",
    ),
    path(
        "<int:pk>/documents/carte/<uuid:document_id>/confirmer/",
        document_views.identity_confirm,
        name="identity_confirm",
    ),
    path(
        "<int:pk>/documents/carte/<int:card_id>/annuler/",
        document_views.identity_undo,
        name="identity_undo",
    ),
    path("<int:pk>/documents/fiche-risque/remplir/", risk_views.risk_sheet, name="risk_sheet"),
    path(
        "<int:pk>/documents/fiche-risque/<int:assessment_id>/valider/",
        risk_views.risk_approve,
        name="risk_approve",
    ),
    path("<int:pk>/documents/<slug:slug>/", document_views.case_page, name="document_case"),
    # Actions
    path("<int:pk>/modifier/", views.client_edit, name="edit"),
    path("<int:pk>/numero-national/", views.reveal_national_number, name="reveal_nn"),
    path(
        "<int:pk>/sites-officiels/<slug:source>/actualiser/",
        views.official_refresh,
        name="official_refresh",
    ),
    path(
        "<int:pk>/bce-tva/fonction/<int:index>/reprendre/",
        views.official_function_add,
        name="official_function_add",
    ),
    path("<int:pk>/equipe/modifier/", views.assignments_edit, name="assignments"),
    path("<int:pk>/coordonnees/ajouter/", views.contact_add, name="contact_add"),
    path("<int:pk>/coordonnees/contact/", views.contact_person, name="contact_person"),
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
]
