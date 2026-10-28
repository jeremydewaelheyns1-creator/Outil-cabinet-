"""Corbeille des dossiers clients (D-095).

« Supprimer » un dossier le met à la corbeille : il disparaît partout (listes, recherche,
tableaux, échéances futures, relances, consultations automatiques), mais rien n'est effacé —
les documents anti-blanchiment doivent être gardés 10 ans. Un administrateur le retrouve dans
Clients › Corbeille et le réactive d'un clic : tout revient tel quel.

Réservé aux administrateurs ; chaque mise à la corbeille et chaque réactivation est tracée
(historique de la fiche, journal des consultations, événement).
"""

from __future__ import annotations

from collections.abc import Iterable

from django.db import transaction
from django.utils import timezone

from apps.core import events
from apps.core.models import User

from .models import Client


def to_trash(clients: Iterable[Client], *, user: User | None) -> int:
    from apps.documents import services as documents
    from apps.documents.models import DocumentRequest

    count = 0
    for client in clients:
        if client.deleted_at is not None:
            continue
        with transaction.atomic():
            client.deleted_at, client.deleted_by = timezone.now(), user
            client.save(update_fields=["deleted_at", "deleted_by", "updated_at"])
            # Plus aucun e-mail ni relance au client d'un dossier supprimé.
            for request in DocumentRequest.objects.filter(
                client=client, status=DocumentRequest.Status.PENDING, bundle__isnull=True
            ):
                documents.cancel(request, user=user)
        events.emit("client.deleted", subject=client, actor=user)
        count += 1
    return count


def restore(clients: Iterable[Client], *, user: User | None) -> int:
    count = 0
    for client in clients:
        if client.deleted_at is None:
            continue
        client.deleted_at, client.deleted_by = None, None
        client.save(update_fields=["deleted_at", "deleted_by", "updated_at"])
        events.emit("client.restored", subject=client, actor=user)
        count += 1
    return count
