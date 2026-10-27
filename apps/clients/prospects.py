"""Prospect → client à la signature de la lettre de mission (D-077).

La lettre de mission est souvent envoyée avant que la personne soit cliente : on crée alors
une fiche « Prospect » (aucune échéance, aucune demande de documents : les automatismes ne
travaillent que sur les clients). Quand la lettre revient signée, la fiche passe en « Client »
et l'expert-comptable du dossier (le « Responsable ») reçoit une notification dans l'outil
avec ce qu'il reste à compléter. Sans responsable : les associés, puis les administrateurs.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core import events
from apps.core.models import Event, Notification, User

from .models import Assignment, Client, ContactPoint


def missing_information(client: Client) -> list[str]:
    """Ce qu'une fiche de client actif doit avoir et que la fiche prospect n'a pas encore."""
    missing = []
    if not client.vat_status:
        missing.append("statut TVA")
    if not client.is_person and not client.fiscal_year_end_month:
        missing.append("date de clôture de l'exercice")
    if not client.assignments.exists():
        missing.append("équipe du dossier")
    if not client.contacts.filter(kind=ContactPoint.Kind.EMAIL).exists():
        missing.append("adresse e-mail")
    return missing


def _recipients(client: Client) -> list[User]:
    team = {a.role: a.user for a in client.assignments.select_related("user")}
    for role in (Assignment.Role.MANAGER, Assignment.Role.PARTNER):
        if team.get(role) is not None and team[role].is_active:
            return [team[role]]
    return list(User.objects.filter(is_staff=True, is_active=True))


def become_client(client: Client, *, actor: User | None = None, reason: str = "") -> bool:
    """Passe la fiche en « Client » (une seule fois) et prévient l'expert-comptable."""
    if client.status != Client.Status.PROSPECT:
        return False
    today = timezone.localdate()
    with transaction.atomic():
        client.status = Client.Status.ACTIVE
        client.client_since = client.client_since or today
        client.save(update_fields=["status", "client_since", "updated_at"])
    events.emit("client.became_client", subject=client, actor=actor, payload={"raison": reason})
    events.emit("client.updated", subject=client, actor=actor)  # échéances du nouveau client
    lines = [f"{reason or 'Devenu client'} le {today:%d/%m/%Y}."]
    todo = missing_information(client)
    if todo:
        lines.append("À compléter dans la fiche : " + ", ".join(todo) + ".")
    lines.append("Puis le dossier anti-blanchiment et les mandats SPF (onglet Documents).")
    for user in _recipients(client):
        Notification.objects.get_or_create(
            user=user,
            key=f"nouveau-client:{client.pk}",
            defaults={
                "title": f"Nouveau client : {client.display_name}",
                "lines": lines,
                "link": client.get_absolute_url(),
            },
        )
    return True


@events.on("document.signed")
def prospect_signs_the_letter(event: Event) -> None:
    """Idempotent : une fiche déjà cliente n'est pas touchée."""
    from apps.documents.models import Document

    document_id = str((event.payload or {}).get("document") or "")
    if not document_id:
        return
    document = Document.objects.filter(pk=document_id).select_related("client").first()
    if document is None or document.doc_type != "lettre_mission":
        return
    become_client(document.client, reason="Lettre de mission signée en ligne")
