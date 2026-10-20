"""Dépôt unique de documents pour tout l'outil (D-041).

On dépose n'importe quel fichier à un seul endroit (barre du haut) ; l'outil cherche seul le
dossier et la place :
1. XML d'Intervat (déclaration TVA, listing IC) → grille TVA du bon dossier (D-040) ;
2. PDF d'Intervat → rejoint sa déclaration (ou « à confirmer » dans le bon dossier) ;
3. carte d'identité (photo ou PDF) → lignes codées lues sur le serveur, personne retrouvée
   par son numéro national → case « Cartes d'identité » de son dossier, où la carte est
   vérifiée et appliquée comme d'habitude (D-035) ;
4. sinon → « À classer » : visible seulement par la personne qui l'a déposé, effacé après
   `INBOX_RETENTION_DAYS` jours s'il n'est pas classé.

Seuls les dossiers visibles par l'utilisateur sont cherchés. Le numéro national lu sur une
carte sert seulement à la recherche : il n'est ni conservé, ni journalisé, ni affiché.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from django.db.models import QuerySet
from django.urls import reverse
from django.utils import timezone

from apps.clients import dossier
from apps.clients.models import Client, Relation
from apps.core import events
from apps.core.models import User
from apps.vat import importer, intervat
from apps.vat.models import VatFiling

from . import identity, mrz
from . import services as documents
from .models import Document, InboxItem

OK = "ok"  # rangé dans son dossier
DOUBT = "doubt"  # rangé dans son dossier, un détail à confirmer
INBOX = "inbox"  # pas reconnu : « À classer »
ERROR = "error"  # refusé (format, taille)

XML = "application/xml"
PDF = "application/pdf"
IMAGES = ("image/jpeg", "image/png")


@dataclass
class Result:
    name: str
    level: str
    message: str
    client: Client | None = None
    url: str = ""


def _content(upload: UploadedFile[bytes]) -> bytes:
    upload.seek(0)
    content = bytes(upload.read())
    upload.seek(0)
    return content


def _check(upload: UploadedFile[bytes]) -> str:
    if not upload.size:
        raise ValidationError("Le fichier est vide.")
    if upload.size > settings.DOCUMENT_MAX_BYTES:
        limit = settings.DOCUMENT_MAX_BYTES // (1024 * 1024)
        raise ValidationError(f"Fichier trop lourd (maximum {limit} Mo).")
    return documents.detect_type(upload).content_type


def to_inbox(upload: UploadedFile[bytes], content_type: str, user: User, reason: str) -> Result:
    content = _content(upload)
    item = InboxItem(
        original_name=(upload.name or "document")[-255:],
        content_type=content_type,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        reason=reason[:200],
        uploaded_by=user,
    )
    item.file.save("document", ContentFile(content), save=False)
    item.save()
    return Result(item.original_name, INBOX, f"À classer : {reason}")


# --- Déclarations TVA (Intervat) -------------------------------------------------------------


def _from_vat(outcome: importer.Outcome) -> Result:
    url = reverse("clients:vat", args=[outcome.client.pk]) if outcome.client else ""
    level = DOUBT if outcome.level == importer.DOUBT else OK
    return Result(outcome.name, level, outcome.message, outcome.client, url)


# --- Cartes d'identité -----------------------------------------------------------------------


def _card_dossier(person: Client, clients: QuerySet[Client]) -> Client:
    """Le dossier de la personne si elle est cliente, sinon une société qu'elle dirige ou dont
    elle est actionnaire (la carte compte pour tous ses dossiers)."""
    if person.status == Client.Status.ACTIVE:
        return person
    ids = Relation.objects.current().filter(person=person).values_list("entity_id", flat=True)
    company = clients.filter(pk__in=ids).order_by("name").first()
    return company or person


def _identity_card(
    upload: UploadedFile[bytes], content_type: str, clients: QuerySet[Client], user: User
) -> Result | None:
    text = identity.CARD_READER(_content(upload), content_type)
    result = mrz.read(text) if text else None
    del text  # le texte lu (avec le numéro national) ne quitte pas cette fonction
    if result is None or not result.valid or not result.document_code.startswith("I"):
        return None
    found = list(
        clients.filter(kind=Client.Kind.PERSON, national_number=result.national_number)[:2]
    )
    if len(found) != 1:
        return to_inbox(upload, content_type, user,
                        "carte d'identité lue, mais aucune fiche ne correspond")  # fmt: skip
    person = found[0]
    target = _card_dossier(person, clients)
    document = documents.store(
        target, upload, title=f"Carte d'identité de {person.display_name}",
        case=identity.CASE, person=person, user=user,
    )  # fmt: skip
    # Vérifiée tout de suite, comme dans la case (D-035) : appliquée, ou à confirmer.
    document.refresh_from_db()
    if not document.review_needed and not document.identity_cards.exists():
        identity.process(document, user=user)
    url = reverse("clients:document_case", args=[target.pk, identity.CASE])
    name = upload.name or "carte"
    if document.identity_cards.exists():
        return Result(name, OK, f"Carte d'identité de {person.display_name} rangée et "
                      "enregistrée (tous les contrôles sont verts).", target, url)  # fmt: skip
    return Result(name, DOUBT, f"Carte d'identité de {person.display_name} rangée, à "
                  f"confirmer : {document.review_reason or 'vérification à faire'}.", target,
                  url)  # fmt: skip


# --- Point d'entrée --------------------------------------------------------------------------


def receive(
    uploads: Sequence[UploadedFile[bytes]], *, clients: QuerySet[Client], user: User
) -> list[Result]:
    results: list[Result] = []
    accepted: list[tuple[UploadedFile[bytes], str]] = []
    for upload in uploads:
        try:
            accepted.append((upload, _check(upload)))
        except ValidationError as error:
            results.append(Result(upload.name or "fichier", ERROR, " ".join(error.messages)))
    classified: list[tuple[intervat.Declaration, VatFiling]] = []
    # Les XML d'abord : un PDF déposé avec son XML le rejoint.
    for upload, content_type in accepted:
        if content_type != XML:
            continue
        outcome = importer.import_xml(upload, clients, user, classified)
        if outcome.level == importer.ERROR:
            results.append(to_inbox(upload, content_type, user, outcome.message))
        else:
            results.append(_from_vat(outcome))
    for upload, content_type in accepted:
        if content_type == XML:
            continue
        if content_type == PDF:
            clues = intervat.read_pdf(_content(upload))
            if clues.looks_like_vat:
                outcome = importer.import_pdf(upload, clients, user, classified, clues)
                if outcome.level != importer.ERROR:
                    results.append(_from_vat(outcome))
                    continue
        if content_type == PDF or content_type in IMAGES:
            card = _identity_card(upload, content_type, clients, user)
            if card is not None:
                results.append(card)
                continue
        results.append(to_inbox(upload, content_type, user, "document non reconnu"))
    for result in results:
        if result.client is not None:
            events.emit("inbox.filed", subject=result.client, actor=user,
                        payload={"niveau": result.level})  # fmt: skip
    return results


# --- « À classer » ---------------------------------------------------------------------------


def places(client: Client) -> list[tuple[str, str]]:
    """Où ranger à la main : les cases de l'onglet Documents puis les archives du dossier."""
    choices = [
        (f"case:{c.slug}", f"Documents › {c.label}")
        for c in dossier.document_cases_for(client)
        if c.slug != "a-recevoir"
    ]
    choices += [
        (f"folder:{s.slug}", f"Archives › {s.label}")
        for g in dossier.side_for(client)
        for s in g.sections
        if s.is_folder
    ]
    return choices


def classify(item: InboxItem, client: Client, place: str, title: str, user: User) -> Document:
    kind, _, slug = place.partition(":")
    if place not in {value for value, _ in places(client)}:
        raise ValueError("Endroit inconnu.")
    with item.file.open("rb") as handle:
        upload = SimpleUploadedFile(item.original_name, handle.read(), item.content_type)
    document = documents.store(
        client, upload, title=title.strip() or item.original_name,
        case=slug if kind == "case" else "", folder=slug if kind == "folder" else "", user=user,
    )  # fmt: skip
    discard(item)
    return document


def discard(item: InboxItem) -> None:
    item.file.delete(save=False)
    item.delete()


def purge(now: datetime | None = None) -> int:
    """Efface les fichiers non classés après le délai de conservation."""
    limit = (now or timezone.now()) - timedelta(days=settings.INBOX_RETENTION_DAYS)
    count = 0
    for item in InboxItem.objects.filter(uploaded_at__lt=limit):
        discard(item)
        count += 1
    return count
