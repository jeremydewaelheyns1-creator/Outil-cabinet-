"""Dossier actif, disponible dans tous les gabarits (en-tête, onglets, panneau de gauche)."""

from typing import Any

from django.db.models import Q
from django.http import HttpRequest

from apps.core.models import User

from . import dossier
from .models import Client, Relation


def current_dossier(request: HttpRequest) -> dict[str, Any]:
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    client = dossier.current(request)
    if client is None:
        return {"current_client": None, "current_section": dossier.section_of(request)}
    overdue = _overdue(client)
    return {
        "current_client": client,
        "current_section": dossier.section_of(request),
        "dossier_top": dossier.top_for(client),
        "dossier_side": dossier.side_for(client, user),
        "dossier_counts": {
            **_relation_counts(client, user),
            "overdue": overdue,
            "archives": _archives(client),
        },
        "dossier_overdue": overdue,
        "dossier_unanswered": _unanswered(client),
        "dossier_progress": _progress(client),
        "dossier_relations": dossier.header_relations(client, user),
        "dossier_hybrid": _hybrid(client),
    }


def _hybrid(client: Client) -> dict[str, Any] | None:
    """Gestion hybride (D-063) : libre, ou pris par qui (pour ne pas travailler à deux)."""
    from . import hybrid

    if not hybrid.is_hybrid(client):
        return None
    from .models import HybridClaim

    return {"claim": HybridClaim.objects.filter(client=client).select_related("user").first()}


def _overdue(client: Client) -> int:
    from apps.tasks.models import Task  # le module échéances dépend des clients

    return Task.objects.filter(client=client).overdue().count()


def _relation_counts(client: Client, user: User) -> dict[str, int]:
    """Compteurs du panneau « Organisation » (relations en cours, fiches visibles)."""
    visible = Client.objects.visible_to(user)
    current = Relation.objects.current()
    if client.is_person:
        base = current.filter(
            Q(person=client, entity__in=visible) | Q(entity=client, person__in=visible)
        )
    else:
        base = current.filter(entity=client, person__in=visible)
    counts = {
        "mandates": base.filter(role__in=dossier.RELATION_PAGES["mandates"]).count(),
        "shareholders": base.filter(role__in=dossier.RELATION_PAGES["shareholders"]).count(),
    }
    return counts


def _unanswered(client: Client) -> int:
    from apps.documents.services import unanswered  # les documents dépendent des clients

    return int(unanswered().filter(client=client).count())


def _progress(client: Client) -> dict[str, int]:
    from apps.documents.compliance import progress

    return progress(client)


def _archives(client: Client) -> int:
    """Nombre de documents du classeur « Archives » (D-105)."""
    from apps.documents.models import Document  # les documents dépendent des clients

    return Document.objects.filter(client=client, folder__in=dossier.CLASSEUR_FOLDERS).count()
