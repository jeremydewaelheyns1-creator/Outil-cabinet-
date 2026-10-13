"""Automatismes liés à la BCE, déclenchés par le journal d'événements."""

from apps.clients.models import Client
from apps.core import events
from apps.core.models import Event

from . import services


def _client(event: Event) -> Client | None:
    if not event.subject_id:
        return None
    return Client.objects.filter(pk=event.subject_id).first()


@events.on("client.created")
@events.on("client.enterprise_number_changed")
def enrich_new_client(event: Event) -> None:
    """Nouveau client (ou nouveau numéro) : on complète la fiche avec la BCE."""
    client = _client(event)
    if client is not None:
        services.fill_blanks(client)


@events.on("bce.enterprise_changed")
def refresh_public_fields(event: Event) -> None:
    """La BCE signale un changement : statut, situation juridique et activités sont réalignés.

    Les différences sur le nom ou l'adresse restent proposées sur la fiche du client.
    """
    client = _client(event)
    if client is None or not client.enterprise_number:
        return
    services.sync_public_fields(client, services.lookup(client.enterprise_number))
