"""Prospect → client à la signature de la lettre de mission (D-077).

La lettre de mission est souvent envoyée avant que la personne soit cliente : on crée alors
une fiche « Prospect » (aucune échéance, aucune demande de documents : les automatismes ne
travaillent que sur les clients). Quand la lettre revient signée, la fiche passe en « Client »
et l'expert-comptable du dossier (le « Responsable ») reçoit une notification dans l'outil
avec ce qu'il reste à compléter. Sans responsable : les associés, puis les administrateurs.
"""

from __future__ import annotations

from typing import Any

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


STALE_DAYS = 365  # D-077 : un prospect sans suite depuis un an est proposé à la suppression


def remind_stale(today: object = None) -> int:
    """Une fois par mois, les administrateurs voient combien de prospects n'ont pas donné suite
    depuis un an. L'outil ne supprime rien lui-même : l'humain décide (données personnelles à
    ne pas garder sans raison)."""
    from datetime import date, timedelta

    day = today if isinstance(today, date) else timezone.localdate()
    limit = timezone.now() - timedelta(days=STALE_DAYS)
    count = Client.objects.filter(status=Client.Status.PROSPECT, updated_at__lt=limit).count()
    if not count:
        return 0
    for user in User.objects.filter(is_staff=True, is_active=True):
        Notification.objects.get_or_create(
            user=user,
            key=f"prospects-sans-suite:{day:%Y-%m}",
            defaults={
                "title": f"{count} prospect{'s' if count > 1 else ''} sans suite depuis un an",
                "lines": ["À supprimer s'ils n'ont pas donné suite : leurs données ne doivent "
                          "pas être gardées sans raison."],
                "link": "/clients/?statut=prospect",
            },
        )  # fmt: skip
    return count


def _delete_files(files: list[tuple[Any, str]]) -> None:
    for storage, name in files:
        storage.delete(name)


def delete_prospect(client: Client) -> None:
    """Efface un prospect sans suite et tout ce qui le concerne : documents (et leurs
    fichiers), demandes, preuves de signature, fiches de risque, coordonnées, relations et
    l'historique de sa fiche. Seulement pour un prospect ; journalisé par la vue (D-077)."""
    from django.db.models import Q

    from apps.documents.models import (
        Document,
        DocumentRequest,
        IdentityCard,
        RiskAssessment,
        Signature,
    )  # fmt: skip

    from .models import Relation

    if client.status != Client.Status.PROSPECT:
        raise ValueError("Seul un prospect peut être supprimé.")
    pk = client.pk
    with transaction.atomic():
        documents = Document.objects.filter(Q(client=client) | Q(person=client))
        requests = DocumentRequest.objects.filter(Q(client=client) | Q(person=client))
        files = [(d.file.storage, d.file.name) for d in documents if d.file and d.file.name]
        Signature.objects.filter(Q(document__in=documents) | Q(request__in=requests)).delete()
        IdentityCard.objects.filter(person=client).delete()
        RiskAssessment.objects.filter(client=client).delete()
        Document.objects.filter(pk__in=documents.values("pk")).update(request=None)
        Document.objects.filter(pk__in=[d.pk for d in documents]).delete()
        requests.update(bundle=None)
        DocumentRequest.objects.filter(pk__in=[r.pk for r in requests]).delete()
        client.delete()
        # Après la suppression (qui ajoute elle-même une ligne d'historique) : rien ne reste.
        for model in (Client, Relation, ContactPoint, Assignment):
            history = model.history.model
            if model is Client:
                history.objects.filter(id=pk).delete()
            elif model is Relation:
                history.objects.filter(Q(entity_id=pk) | Q(person_id=pk)).delete()
            else:
                history.objects.filter(client_id=pk).delete()
        transaction.on_commit(lambda: _delete_files(files))
    events.emit("client.prospect_deleted", payload={"fiche": pk})
