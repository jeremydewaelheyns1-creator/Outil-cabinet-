"""Types de documents exigés par la loi anti-blanchiment, et leur situation (D-037).

Chaque type dit dans quelle case il se range, s'il en faut un par personne (mandataire), s'il
expire, s'il est obligatoire, qui le fournit (client ou cabinet) et où il part aux archives
quand un nouveau le remplace. À partir de là, l'outil sait seul ce qui manque, ce qui expire
et ce qu'il faut demander au client : une ligne par type et par personne, comme FID-Manager.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.utils import timezone

from apps.clients.models import Client, Relation

from .models import Document

WARN_DAYS = 60


@dataclass(frozen=True)
class DocType:
    slug: str
    label: str
    case: str
    archive_folder: str
    per: str = ""  # "" (un pour le dossier) ou "mandataire" (un par mandataire)
    expires: bool = False
    required: bool = True
    from_client: bool = False  # le client le fournit (on peut le lui demander)
    for_persons: bool = True  # concerne aussi un client personne physique (IPP)


TYPES: tuple[DocType, ...] = (
    DocType("lettre_mission", "Lettre de mission", "lettre-de-mission", "legal", from_client=True),
    DocType(
        "identification_client", "Identification du client", "anti-blanchiment", "administratif"
    ),
    DocType(
        "identification_mandataire",
        "Identification des mandataires",
        "anti-blanchiment",
        "administratif",
        per="mandataire",
        for_persons=False,
    ),
    DocType(
        "fiche_risque",
        "Fiche de détermination du niveau de risque",
        "anti-blanchiment",
        "administratif",
        expires=True,
    ),
    DocType(
        "procuration", "Procuration", "anti-blanchiment", "legal", required=False, from_client=True
    ),
    DocType(
        "declaration_ubo",
        "Déclaration des bénéficiaires effectifs",
        "ubo",
        "legal",
        from_client=True,
        for_persons=False,
    ),
    DocType(
        "extrait_ubo",
        "Extrait du registre UBO",
        "ubo",
        "legal",
        expires=True,
        for_persons=False,
    ),
    DocType("autre", "Autre document", "", "administratif", required=False),
)
BY_SLUG = {t.slug: t for t in TYPES}
CARD = "carte_identite"  # les cartes d'identité ont leur propre suivi (identity.py)


def types_for_case(case: str, client: Client | None = None) -> list[DocType]:
    return [
        t
        for t in TYPES
        if t.case == case and (client is None or t.for_persons or not client.is_person)
    ]


def mandataires(client: Client) -> list[Client]:
    """Mandataires en cours (personnes ou sociétés) : un document d'identification chacun."""
    ids = (
        Relation.objects.current()
        .filter(
            entity=client,
            role__in=(*Relation.MANAGEMENT_ROLES, Relation.Role.PERMANENT_REPRESENTATIVE),
        )
        .values_list("person_id", flat=True)
    )
    return list(Client.objects.filter(pk__in=ids).order_by("name", "first_name"))


@dataclass(frozen=True)
class Row:
    """Une ligne de la case : un type de document (et une personne), sa situation."""

    doc_type: DocType
    person: Client | None
    document: Document | None
    level: str  # ok / warning / danger / empty (facultatif absent)
    text: str

    @property
    def days_left(self) -> int | None:
        if self.document is None or self.document.expires_on is None:
            return None
        return (self.document.expires_on - timezone.localdate()).days


def _situation(doc_type: DocType, document: Document | None, today: date) -> tuple[str, str]:
    if document is None:
        return ("danger", "Manquant") if doc_type.required else ("empty", "Aucun")
    if not doc_type.expires:
        return "ok", ""
    if document.expires_on is None:
        return "warning", "Date d'expiration indéfinie"
    if document.expires_on < today:
        return "danger", f"Expiré depuis le {document.expires_on:%d/%m/%Y}"
    if document.expires_on <= today + timedelta(days=WARN_DAYS):
        days = (document.expires_on - today).days
        return "warning", f"Expire dans {days} jour{'s' if days > 1 else ''}"
    return "ok", ""


def rows(client: Client, case: str) -> list[Row]:
    today = timezone.localdate()
    current = list(
        Document.objects.filter(client=client, case=case, archived_at__isnull=True)
        .select_related("person")
        .order_by("-uploaded_at")
    )
    result: list[Row] = []
    for doc_type in types_for_case(case, client):
        targets: list[Client | None] = (
            list(mandataires(client)) if doc_type.per == "mandataire" else [None]
        )
        for person in targets:
            document = next(
                (
                    d
                    for d in current
                    if d.doc_type == doc_type.slug and (person is None or d.person_id == person.pk)
                ),
                None,
            )
            level, text = _situation(doc_type, document, today)
            result.append(Row(doc_type, person, document, level, text))
    return result


def worst(levels: list[str]) -> str:
    for level in ("danger", "warning", "ok"):
        if level in levels:
            return level
    return "empty"
