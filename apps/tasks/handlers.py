"""Les échéances suivent les changements de la fiche client."""

from apps.clients.models import Client
from apps.core import events
from apps.core.models import Event

from .generator import generate_for_client, reassign_open_tasks


@events.on("client.created")
@events.on("client.updated")
@events.on("client.updated_from_bce")
@events.on("client.deleted")  # corbeille : les échéances futures non commencées partent (D-095)
@events.on("client.restored")  # réactivé : elles reviennent
def regenerate_client_tasks(event: Event) -> None:
    client = _client(event)
    if client is not None:
        generate_for_client(client)


@events.on("client.team_changed")
def follow_team_change(event: Event) -> None:
    client = _client(event)
    if client is not None:
        reassign_open_tasks(client)


def _client(event: Event) -> Client | None:
    return Client.objects.filter(pk=event.subject_id).first() if event.subject_id else None
