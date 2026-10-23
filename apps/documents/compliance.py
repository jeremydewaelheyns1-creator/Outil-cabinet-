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

from dataclasses import dataclass, field
from typing import Any

from apps.clients import dossier
from apps.clients.models import Client

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


def overview(client: Client) -> Overview:
    result = Overview(client=client, has_email=bool(services._recipient(client)))
    pending = services.pending_requests(client)
    result.pending = len(pending)
    pending_keys = {(r.doc_type, r.person_id) for r in pending if r.doc_type}
    for case in dossier.document_cases_for(client):
        if case.slug not in types.TYPED_CASES:
            continue
        for row in types.rows(client, case.slug):
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
    people = services.people_concerned(client)
    for card in identity.people_cards(client, people):
        if card.level not in ("danger", "warning"):
            continue
        name = card.person.display_name
        result.lines.append(Line(f"Carte d'identité — {name} : {card.text}", card.level))
        if card.pending is None and card.text != "Nouvelle carte reçue, à confirmer":
            result.askable.append(("carte", card.person))
            result.askable_labels.append(f"Carte d'identité de {name}")
    return result


def board(clients: list[Client]) -> list[Overview]:
    rows = [overview(c) for c in clients]
    rows = [r for r in rows if r.lines or r.pending]
    order = {"danger": 0, "warning": 1, "ok": 2}
    return sorted(rows, key=lambda r: (order[r.level], -r.missing, r.client.display_name))


def ask_everything(client: Client, user: Any) -> DocumentRequest | None:
    """Une seule demande au client pour tout ce qui peut lui être demandé maintenant."""
    found = overview(client)
    if not found.askable or not found.has_email:
        return None
    return services.create_bundle(client, found.askable, user=user)
