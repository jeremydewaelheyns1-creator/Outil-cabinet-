"""Pièces d'identité : lecture de la carte reçue, vérifications, mise à jour, relances (D-035).

Chaîne complète :
1. une carte arrive (dépôt ou réponse à une demande) dans la case « Pièces d'identité » ;
2. l'outil lit les lignes « machine » au dos (OCR local, aucun service extérieur) ;
3. il vérifie tout : chiffres de contrôle, type de document, nom, numéro national (ou date de
   naissance), validité ;
4. tout est vert → la carte est enregistrée sans confirmation (D-032), visible dans « Classé
   automatiquement » et annulable 7 jours ; sinon → le document est « à confirmer » ;
5. chaque jour, `request_renewals` demande la nouvelle carte avant expiration.

Le texte lu et le numéro national qu'il contient ne sont ni conservés, ni journalisés, ni
affichés.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.clients.models import Client, ContactPoint, Relation
from apps.core import events
from apps.core.models import Event, User
from apps.integrations.official_parsers import normalize

from . import mrz
from .models import Document, DocumentRequest, IdentityCard

logger = logging.getLogger(__name__)
CASE = "pieces-identite"
UNDO_DAYS = 7
WARN_DAYS = 15  # orange (et demande au client) quand la carte expire dans 15 jours (D-054)


# --- Lecture (OCR local) ---------------------------------------------------------------------


def _run(command: list[str], timeout: int = 60) -> str:
    result = subprocess.run(  # noqa: S603 (commande fixe, aucun texte venant de l'utilisateur)
        command, capture_output=True, text=True, timeout=timeout, check=False
    )
    return result.stdout


def ocr_bytes(content: bytes, content_type: str) -> str | None:
    """Texte lu sur la photo (ou les 2 premières pages du PDF), en cherchant et redressant la
    bande des lignes « machine » (`card_reader`). Tout se passe sur le serveur du cabinet ; les
    fichiers temporaires sont effacés aussitôt."""
    if not settings.IDENTITY_OCR_ENABLED or not shutil.which("tesseract"):
        return None
    if content_type not in ("image/jpeg", "image/png", "application/pdf"):
        return None
    from . import card_reader

    def is_valid(text: str) -> bool:
        result = mrz.read(text)
        return bool(result and result.valid)

    if content_type != "application/pdf":
        return card_reader.read(content, is_valid)
    if not shutil.which("pdftoppm"):
        return None
    with tempfile.TemporaryDirectory(prefix="lecture-") as folder:
        source = Path(folder) / "source"
        source.write_bytes(content)
        _run(["pdftoppm", "-r", "300", "-png", "-f", "1", "-l", "2", str(source),
              f"{folder}/page"])  # fmt: skip
        texts = []
        for image in sorted(Path(folder).glob("page*.png")):
            text = card_reader.read(image.read_bytes(), is_valid, budget=20.0)
            if is_valid(text):
                return text
            texts.append(text)
        return "\n".join(texts)


def ocr_text(document: Document) -> str | None:
    with document.file.open("rb") as handle:
        return CARD_READER(handle.read(), document.content_type)


# Points d'entrée remplaçables (tests ; plus tard, lecture par IA dans le cloud du cabinet).
CARD_READER: Callable[[bytes, str], str | None] = ocr_bytes
READER: Callable[[Document], str | None] = ocr_text


# --- Vérifications ---------------------------------------------------------------------------


def _one_typo_apart(a: str, b: str) -> bool:
    """Vrai si une seule lettre diffère (ajoutée, perdue ou changée)."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) <= 1
    short, long = (a, b) if len(a) < len(b) else (b, a)
    return any(long[:i] + long[i + 1 :] == short for i in range(len(long)))


def _name_found(name: str, read_names: set[str], same_number: bool) -> bool:
    """Le nom de la fiche est-il sur la carte ? Une seule lettre mal lue est tolérée, et
    seulement quand le numéro national lu (vérifié par ses chiffres de contrôle) est celui de
    la fiche : c'est lui qui prouve l'identité, le nom ne fait que confirmer."""
    if name in read_names:
        return True
    return same_number and len(name) >= 4 and any(_one_typo_apart(name, r) for r in read_names)


def problems(result: mrz.MrzResult | None, person: Client, today: date) -> list[str]:
    """Ce qui empêche d'appliquer la carte sans confirmation (liste vide = tout est vert)."""
    if result is None:
        return ["Lignes « machine » illisibles (photo du dos de la carte nette et entière ?)"]
    issues = []
    if not result.valid:
        issues.append("Contrôle de lecture échoué : " + ", ".join(result.failed_checks))
    if not result.document_code.startswith("I"):
        issues.append("Ce document n'est pas une carte d'identité")
    read_names = set(normalize(f"{result.surname} {result.given_names}").split())
    file_names = set(normalize(f"{person.name} {person.first_name}").split())
    same_number = bool(person.national_number) and result.national_number == person.national_number
    if not file_names or not all(_name_found(n, read_names, same_number) for n in file_names):
        issues.append("Le nom lu ne correspond pas à la fiche")
    if person.national_number:
        if not same_number:
            issues.append("Le numéro national ne correspond pas à la fiche")
    elif person.birth_date:
        if result.birth_date != person.birth_date:
            issues.append("La date de naissance ne correspond pas à la fiche")
    else:
        issues.append("Fiche sans numéro national ni date de naissance : vérification impossible")
    if result.expiry_date is None or result.expiry_date < today:
        issues.append("Carte expirée")
    return issues


def process(document: Document, *, user: User | None = None) -> IdentityCard | None:
    """Lit la carte reçue et l'applique si tout est vert ; sinon la marque « à confirmer »."""
    person = document.person
    if person is None:
        _to_confirm(document, "Personne concernée non indiquée")
        return None
    text = READER(document)
    result = mrz.read(text) if text else None
    del text  # le texte lu (avec le numéro national) ne quitte pas cette fonction
    issues = problems(result, person, timezone.localdate())
    if issues or result is None or result.expiry_date is None:
        _to_confirm(document, issues[0] if issues else "Lecture incomplète")
        return None
    with transaction.atomic():
        card = IdentityCard.objects.create(
            person=person,
            document=document,
            card_number=result.document_number,
            valid_until=result.expiry_date,
            source=IdentityCard.Source.READ,
            auto_applied=True,
            created_by=user,
        )
        document.auto_filed = True
        document.review_needed = False
        document.review_reason = ""
        document.save(update_fields=["auto_filed", "review_needed", "review_reason"])
    events.emit(
        "identity_card.applied",
        subject=document.client,
        actor=user,
        payload={"document": str(document.pk), "person": person.pk, "automatique": True},
    )
    return card


def _to_confirm(document: Document, reason: str) -> None:
    document.review_needed = True
    document.review_reason = reason[:200]
    document.auto_filed = False
    document.save(update_fields=["review_needed", "review_reason", "auto_filed"])


@events.on("document.added")
def read_new_identity_card(event: Event) -> None:
    document_id = str((event.payload or {}).get("document") or "")
    if not document_id:
        return
    document = Document.objects.filter(pk=document_id, case=CASE).first()
    # Déjà lue (dépôt unique, D-041) : on ne la relit pas.
    if document is None or document.review_needed or document.identity_cards.exists():
        return
    process(document)


def confirm(
    document: Document, *, valid_until: date, card_number: str, user: User | None = None
) -> IdentityCard:
    """Le gestionnaire confirme à la main une carte que l'outil n'a pas pu appliquer seul."""
    if document.person is None:
        raise ValueError("Personne concernée manquante.")
    with transaction.atomic():
        card = IdentityCard.objects.create(
            person=document.person,
            document=document,
            card_number=card_number.strip()[:20],
            valid_until=valid_until,
            source=IdentityCard.Source.MANUAL,
            created_by=user,
        )
        document.review_needed = False
        document.review_reason = ""
        document.save(update_fields=["review_needed", "review_reason"])
    events.emit(
        "identity_card.applied",
        subject=document.client,
        actor=user,
        payload={"document": str(document.pk), "person": document.person_id, "automatique": False},
    )
    return card


def can_undo(card: IdentityCard) -> bool:
    return card.auto_applied and card.created_at >= timezone.now() - timedelta(days=UNDO_DAYS)


def undo(card: IdentityCard, *, user: User | None = None) -> None:
    """Annule un classement automatique : la carte redevient « à confirmer »."""
    if not can_undo(card):
        raise ValueError("Ce classement ne peut plus être annulé.")
    document = card.document
    with transaction.atomic():
        card.delete()
        if document is not None:
            _to_confirm(document, "Classement automatique annulé")
    events.emit(
        "identity_card.undone",
        subject=document.client if document else None,
        actor=user,
        payload={"document": str(document.pk) if document else ""},
    )


# --- Situation par personne ------------------------------------------------------------------


@dataclass(frozen=True)
class PersonCard:
    person: Client
    card: IdentityCard | None
    level: str  # ok / warning / danger
    text: str
    pending: DocumentRequest | None

    @property
    def undoable(self) -> bool:
        return self.card is not None and can_undo(self.card)


_NOT_LOADED: Any = object()


def situation(
    person: Client, today: date | None = None, card: IdentityCard | None = _NOT_LOADED
) -> tuple[IdentityCard | None, str, str]:
    today = today or timezone.localdate()
    if card is _NOT_LOADED:
        card = person.identity_cards.order_by("-valid_until", "-created_at").first()
    if card is None:
        return None, "danger", "Aucune carte enregistrée"
    if card.valid_until < today:
        return card, "danger", f"Expirée depuis le {card.valid_until:%d/%m/%Y}"
    if card.valid_until <= today + timedelta(days=WARN_DAYS):
        return card, "warning", f"Expire le {card.valid_until:%d/%m/%Y}"
    return card, "ok", f"Valable jusqu'au {card.valid_until:%d/%m/%Y}"


@dataclass
class Preloaded:
    """Cartes et demandes de plusieurs dossiers chargées en une fois (tableau de conformité)."""

    cards: dict[int, IdentityCard]  # personne → carte la plus récente
    pending: dict[int, DocumentRequest]  # personne → demande de carte en attente
    waiting: dict[int, set[int | None]]  # dossier → personnes dont une carte attend confirmation


def preload(clients: list[Client], people: list[Client]) -> Preloaded:
    person_ids = {p.pk for p in people}
    cards: dict[int, IdentityCard] = {}
    for card in IdentityCard.objects.filter(person_id__in=person_ids).order_by(
        "person_id", "-valid_until", "-created_at"
    ):
        cards.setdefault(card.person_id, card)
    pending = {
        r.person_id: r
        for r in DocumentRequest.objects.filter(
            kind=DocumentRequest.Kind.IDENTITY_CARD,
            status=DocumentRequest.Status.PENDING,
            person_id__in=person_ids,
        )
        if r.person_id is not None
    }
    waiting: dict[int, set[int | None]] = {}
    for client_id, person_id in Document.objects.filter(
        client__in=clients, case=CASE, archived_at__isnull=True, review_needed=True
    ).values_list("client_id", "person_id"):
        waiting.setdefault(client_id, set()).add(person_id)
    return Preloaded(cards, pending, waiting)


def people_cards(
    client: Client, people: list[Client], preloaded: Preloaded | None = None
) -> list[PersonCard]:
    if preloaded is not None:
        pending = preloaded.pending
        waiting = preloaded.waiting.get(client.pk, set())
    else:
        pending = {
            r.person_id: r
            for r in DocumentRequest.objects.filter(
                kind=DocumentRequest.Kind.IDENTITY_CARD,
                status=DocumentRequest.Status.PENDING,
                person__in=people,
            )
            if r.person_id is not None
        }
        waiting = set(
            Document.objects.filter(
                client=client, case=CASE, archived_at__isnull=True, review_needed=True
            ).values_list("person_id", flat=True)
        )
    rows = []
    for person in people:
        if preloaded is not None:
            card, level, text = situation(person, card=preloaded.cards.get(person.pk))
        else:
            card, level, text = situation(person)
        if person.pk in waiting and level != "ok":
            level, text = "warning", "Nouvelle carte reçue, à confirmer"
        rows.append(PersonCard(person, card, level, text, pending.get(person.pk)))
    return rows


def documents_to_confirm(client: Client) -> list[Document]:
    return list(
        Document.objects.filter(
            client=client, case=CASE, archived_at__isnull=True, review_needed=True
        ).select_related("person")
    )


# --- Demandes automatiques avant expiration -------------------------------------------------


def _dossier_for(person: Client) -> Client | None:
    """Dossier où envoyer la demande : celui de la personne si elle est cliente avec une
    adresse e-mail, sinon une société dont elle est mandataire ou actionnaire."""
    candidates = [person]
    company_ids = (
        Relation.objects.current().filter(person=person).values_list("entity_id", flat=True)
    )
    candidates += list(Client.objects.filter(pk__in=company_ids, status=Client.Status.ACTIVE))
    for candidate in candidates:
        if candidate.contacts.filter(kind=ContactPoint.Kind.EMAIL).exists():
            return candidate
    return None


def request_renewals(today: date | None = None) -> int:
    """Demande la nouvelle carte de chaque personne dont la carte expire dans les
    IDENTITY_RENEWAL_DAYS jours, ou a expiré (une seule demande en cours par personne).
    Plusieurs cartes pour le même client : un seul e-mail et un seul lien (D-052)."""
    from . import services

    today = today or timezone.localdate()
    limit = today + timedelta(days=settings.IDENTITY_RENEWAL_DAYS)
    latest: dict[int, IdentityCard] = {}
    for card in IdentityCard.objects.select_related("person").order_by("valid_until"):
        latest[card.person_id] = card
    already = set(
        DocumentRequest.objects.filter(
            kind=DocumentRequest.Kind.IDENTITY_CARD, status=DocumentRequest.Status.PENDING
        ).values_list("person_id", flat=True)
    )
    by_dossier: dict[int, tuple[Client, list[Client]]] = {}
    for person_id, card in latest.items():
        if card.valid_until > limit or person_id in already:
            continue
        dossier = _dossier_for(card.person)
        if dossier is None:
            continue
        by_dossier.setdefault(dossier.pk, (dossier, []))[1].append(card.person)
    count = 0
    for dossier, people in by_dossier.values():
        if len(people) == 1:
            services.create_request(dossier, DocumentRequest.Kind.IDENTITY_CARD, person=people[0])
        else:
            services.create_bundle(dossier, [("carte", person) for person in people])
        count += len(people)
    return count
