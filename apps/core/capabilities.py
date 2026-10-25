"""Catalogue des droits attribuables par profil de sécurité.

Un profil de sécurité est une liste de ces codes. Les administrateurs (superutilisateurs) ont
tout. Ajouter un droit = l'ajouter ici, puis le vérifier dans la vue concernée avec
`require_capability` ou `user.has_capability`.
"""

from django.db import models


class Capability(models.TextChoices):
    CLIENTS_EDIT = "clients.edit", "Créer et modifier les fiches clients"
    CLIENTS_SENSITIVE = (
        "clients.sensitive",
        "Voir les données sensibles (numéro national, pièces d'identité)",
    )
    AML_VIEW = "aml.view", "Consulter les dossiers anti-blanchiment"
    AML_DECIDE = "aml.decide", "Décider en matière d'anti-blanchiment (AMLCO)"
    BILLING_VIEW = "billing.view", "Consulter la facturation"
    TIMESHEET_ALL = "timesheet.all", "Voir les feuilles de temps de toute l'équipe"
    DATA_EXPORT = "data.export", "Exporter des données (Excel, archives)"
    AUDIT_VIEW = "audit.view", "Consulter le journal des consultations"
    REPRISE_IMPORT = "reprise.import", "Importer des données de reprise (FID-Manager)"
    BCE_IMPORT = "bce.import", "Importer les fichiers de la BCE"
