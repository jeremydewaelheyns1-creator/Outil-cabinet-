"""Tableau de conformité du cabinet : ce qui manque, ce qui expire, ce qu'on peut demander (D-051).

Pour chaque dossier visible : les documents anti-blanchiment manquants (rouge), ceux qui
expirent bientôt ou ne sont plus à jour (orange), les demandes en cours. Et ce que l'outil peut
**demander tout de suite au client en un seul e-mail** :
- les cartes d'identité manquantes ou qui expirent (personnes du dossier) ;
- les documents déjà préparés (brouillons relus) qui attendent la signature du client.
Un document jamais préparé n'est pas envoyé d'office : il faut d'abord le générer et le relire
(l'humain décide).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from apps.clients import dossier
from apps.clients.models import Client, ContactPoint, Relation

from . import identity, services, types
from .models import Document, DocumentRequest


@dataclass
class Line:
    label: str
    level: str  # danger / warning


@dataclass
class Overview:
    client: Client
    lines: list[Line] = field(default_factory=list)
    askable: list[tuple[str, Any]] = field(default_factory=list)
    askable_labels: list[str] = field(default_factory=list)
    pending: int = 0
    has_email: bool = False

    @property
    def missing(self) -> int:
        return sum(1 for line in self.lines if line.level == "danger")

    @property
    def soon(self) -> int:
        return sum(1 for line in self.lines if line.level == "warning")

    @property
    def level(self) -> str:
        return "danger" if self.missing else "warning" if self.soon else "ok"


@dataclass
class Batch:
    """Tout ce que `overview` lit, chargé pour beaucoup de dossiers en une dizaine de requêtes
    (au lieu d'une dizaine par dossier) : le tableau reste rapide avec 1 500 dossiers."""

    documents: dict[int, list[Document]]
    mandataires: dict[int, list[Client]]
    people: dict[int, list[Client]]
    emails: set[int]
    pending: dict[int, list[DocumentRequest]]
    cards: identity.Preloaded


def load(clients: list[Client]) -> Batch:
    ids = [c.pk for c in clients]
    documents: dict[int, list[Document]] = defaultdict(list)
    for document in (
        Document.objects.filter(client_id__in=ids, case__in=types.TYPED_CASES,
                                archived_at__isnull=True)
        .select_related("person", "request")
        .order_by("-uploaded_at")
    ):  # fmt: skip
        documents[document.client_id].append(document)
    management = {*Relation.MANAGEMENT_ROLES, Relation.Role.PERMANENT_REPRESENTATIVE}
    links = list(
        Relation.objects.current()
        .filter(entity_id__in=ids)
        .values_list("entity_id", "person_id", "role", "person__kind")
    )
    persons = Client.objects.in_bulk({person for _, person, _, _ in links})
    mandataires: dict[int, list[Client]] = defaultdict(list)
    people: dict[int, list[Client]] = defaultdict(list)
    for entity, person, role, kind in links:
        if role in management and persons[person] not in mandataires[entity]:
            mandataires[entity].append(persons[person])
        if kind == Client.Kind.PERSON and persons[person] not in people[entity]:
            people[entity].append(persons[person])

    def by_name(c: Client) -> tuple[str, str]:
        return (c.name, c.first_name)

    for found in (mandataires, people):
        for entity in found:
            found[entity].sort(key=by_name)
    for client in clients:
        if client.is_person:
            people[client.pk] = [client]
    emails = set(
        ContactPoint.objects.filter(client_id__in=ids, kind=ContactPoint.Kind.EMAIL).values_list(
            "client_id", flat=True
        )
    )
    pending: dict[int, list[DocumentRequest]] = defaultdict(list)
    for request in (
        DocumentRequest.objects.filter(client_id__in=ids, status=DocumentRequest.Status.PENDING)
        .exclude(kind=DocumentRequest.Kind.BUNDLE)
        .select_related("person", "bundle")
    ):
        pending[request.client_id].append(request)
    everyone = [p for group in people.values() for p in group]
    cards = identity.preload(clients, everyone)
    return Batch(documents, mandataires, people, emails, pending, cards)


def overview(client: Client, batch: Batch | None = None) -> Overview:
    if batch is not None:
        result = Overview(client=client, has_email=client.pk in batch.emails)
        pending = batch.pending.get(client.pk, [])
    else:
        result = Overview(client=client, has_email=bool(services._recipient(client)))
        pending = services.pending_requests(client)
    result.pending = len(pending)
    pending_keys = {(r.doc_type, r.person_id) for r in pending if r.doc_type}
    every = (
        types.all_rows(client, batch.documents.get(client.pk, []),
                       batch.mandataires.get(client.pk, []), live=False)
        if batch is not None
        else types.all_rows(client)
    )  # fmt: skip
    for case in dossier.document_cases_for(client):
        if case.slug not in every:
            continue
        for row in every[case.slug]:
            if row.level not in ("danger", "warning"):
                continue
            who = f" — {row.person.display_name}" if row.person else ""
            result.lines.append(Line(f"{row.doc_type.label}{who} : {row.text}", row.level))
            key = (row.doc_type.slug, row.person.pk if row.person else None)
            draft = row.draft
            if (
                key not in pending_keys
                and draft is not None
                and draft.state == Document.State.DRAFT
                and row.needs_signature
            ):
                result.askable.append(("signature", draft))
                result.askable_labels.append(f"{row.doc_type.label}{who} (à signer)")
    if batch is not None:
        people = batch.people.get(client.pk, [])
        cards = identity.people_cards(client, people, batch.cards)
    else:
        cards = identity.people_cards(client, services.people_concerned(client))
    for card in cards:
        if card.level not in ("danger", "warning"):
            continue
        name = card.person.display_name
        result.lines.append(Line(f"Carte d'identité — {name} : {card.text}", card.level))
        if card.pending is None and card.text != "Nouvelle carte reçue, à confirmer":
            result.askable.append(("carte", card.person))
            result.askable_labels.append(f"Carte d'identité de {name}")
    return result


def board(clients: list[Client]) -> list[Overview]:
    batch = load(clients)
    rows = [overview(c, batch) for c in clients]
    rows = [r for r in rows if r.lines or r.pending]
    order = {"danger": 0, "warning": 1, "ok": 2}
    return sorted(rows, key=lambda r: (order[r.level], -r.missing, r.client.display_name))


def ask_everything(client: Client, user: Any) -> DocumentRequest | None:
    """Une seule demande au client pour tout ce qui peut lui être demandé maintenant."""
    found = overview(client)
    if not found.askable or not found.has_email:
        return None
    return services.create_bundle(client, found.askable, user=user)


def summary_for(user: Any) -> dict[str, int]:
    """Nombres pour l'accueil : mes dossiers incomplets / à revoir (gardés 15 minutes).

    Seulement des nombres en mémoire, jamais de nom ni de donnée du dossier."""
    from django.core.cache import cache

    key = f"conformite-accueil:{user.pk}"
    found = cache.get(key)
    if found is None:
        clients = list(
            Client.objects.visible_to(user).active().filter(assignments__user=user).distinct()
        )
        rows = board(clients)
        found = {
            "danger": sum(1 for r in rows if r.level == "danger"),
            "warning": sum(1 for r in rows if r.level == "warning"),
            "askable": sum(1 for r in rows if r.askable and r.has_email),
        }
        cache.set(key, found, 15 * 60)
    return dict(found)


def progress(client: Client) -> dict[str, int]:
    """Avancement du dossier anti-blanchiment pour l'en-tête : documents en ordre / exigés."""
    every = types.all_rows(client)
    levels = [
        row.level
        for case in dossier.document_cases_for(client)
        for row in every.get(case.slug, [])
        if row.level != "empty"
    ]
    people = services.people_concerned(client)
    levels += [card.level for card in identity.people_cards(client, people)]
    total = len(levels)
    done = sum(1 for level in levels if level == "ok")
    return {"done": done, "total": total, "percent": round(100 * done / total) if total else 100}
