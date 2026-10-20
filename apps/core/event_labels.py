"""Libellés lisibles des types d'événements (affichage uniquement)."""

EVENT_LABELS = {
    "client.created": "Fiche créée",
    "client.updated": "Fiche modifiée",
    "client.enterprise_number_changed": "Numéro d'entreprise modifié",
    "client.updated_from_bce": "Données BCE reprises",
    "bce.enterprise_changed": "Changement publié à la BCE",
    "relation.saved": "Relation enregistrée",
    "relation.deleted": "Relation supprimée",
    "official.changed": "Nouveauté sur un site officiel",
    "document.added": "Document ajouté",
    "document.generated": "Document généré par l'outil",
    "document.finalized": "Document généré validé",
    "document_request.created": "Document demandé au client",
    "document_request.received": "Document demandé reçu",
    "document_request.cancelled": "Demande de document annulée",
    "identity_card.applied": "Carte d'identité enregistrée",
    "identity_card.undone": "Classement d'une carte annulé",
    "client.team_changed": "Équipe modifiée",
    "task.completed": "Échéance terminée",
    "task.reopened": "Échéance rouverte",
    "vat.cell_changed": "Suivi TVA modifié",
    "vat.return_imported": "Déclaration TVA importée",
    "inbox.filed": "Document déposé et classé automatiquement",
}


def event_label(event_type: str) -> str:
    return EVENT_LABELS.get(event_type, event_type)
