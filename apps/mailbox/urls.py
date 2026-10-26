from django.urls import path

from . import views

app_name = "boite"

urlpatterns = [
    path("", views.inbox, name="inbox"),
    path("relever/", views.relever, name="relever"),
    path("desactiver/", views.desactiver, name="desactiver"),
    path("nouveau/", views.nouveau, name="nouveau"),
    path("signature/", views.signature, name="signature"),
    path("brouillons/enregistrer/", views.brouillon_enregistrer, name="brouillon_enregistrer"),
    path(
        "brouillons/<int:draft_id>/supprimer/",
        views.brouillon_supprimer,
        name="brouillon_supprimer",
    ),
    path("programmes/<int:item_id>/annuler/", views.programme_annuler, name="programme_annuler"),
    path("programmes/<int:item_id>/envoyer/", views.programme_envoyer, name="programme_envoyer"),
    path("attente/<int:awaiting_id>/fin/", views.plus_attendre, name="plus_attendre"),
    path("piece/<uuid:attachment_id>/", views.piece, name="piece"),
    path("piece/<uuid:attachment_id>/ranger/", views.ranger_piece, name="ranger_piece"),
    path("<uuid:message_id>/classer/", views.classer, name="classer"),
    path("<uuid:message_id>/reclasser/", views.reclasser, name="reclasser"),
    path("<uuid:message_id>/remettre/", views.remettre, name="remettre"),
    path("<uuid:message_id>/prive/", views.prive, name="prive"),
    path("<uuid:message_id>/repondre/", views.repondre, name="repondre"),
    path("<uuid:message_id>/echeance/", views.echeance, name="echeance"),
]
