"""Libellés lisibles des types d'événements (affichage uniquement)."""

EVENT_LABELS = {
    "client.created": "Fiche créée",
    "client.updated": "Fiche modifiée",
    "client.enterprise_number_changed": "Numéro d'entreprise modifié",
    "client.updated_from_bce": "Données BCE reprises",
    "bce.enterprise_changed": "Changement publié à la BCE",
    "relation.saved": "Relation enregistrée",
    "relation.deleted": "Relation supprimée",
}


def event_label(event_type: str) -> str:
    return EVENT_LABELS.get(event_type, event_type)
