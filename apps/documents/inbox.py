"""Dépôt unique de documents pour tout l'outil (D-041).

On dépose n'importe quel fichier à un seul endroit (barre du haut) ; l'outil cherche seul le
dossier et la place :
1. XML d'Intervat (déclaration TVA, listing IC) → grille TVA du bon dossier (D-040) ;
   comptes annuels XBRL de la BNB → page « Comptes annuels » ; déclaration Biztax → ISOC
   (D-098) ;
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
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from django.db import transaction
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
DUPLICATE = "duplicate"  # déjà dans l'outil : retenu, à comparer (D-099)
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
    title: str = ""  # ce qui a été rangé, en clair (panneau de dépôt, D-093)
    where: str = ""  # doublon : le dossier où se trouve déjà le fichier (D-099)


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


def _keep(upload: UploadedFile[bytes], content_type: str, user: User, reason: str,
          duplicate: Document | None = None, intended: dict[str, Any] | None = None,
          ) -> InboxItem:  # fmt: skip
    content = _content(upload)
    item = InboxItem(
        original_name=(upload.name or "document")[-255:],
        content_type=content_type,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        reason=reason[:200],
        uploaded_by=user,
        duplicate_of=duplicate,
        intended=intended or {},
    )
    item.file.save("document", ContentFile(content), save=False)
    item.save()
    return item


def to_inbox(upload: UploadedFile[bytes], content_type: str, user: User, reason: str) -> Result:
    item = _keep(upload, content_type, user, reason)
    return Result(item.original_name, INBOX, f"À classer : {reason}", title=item.original_name)


# --- Déclarations TVA (Intervat) -------------------------------------------------------------


def _from_vat(outcome: importer.Outcome) -> Result:
    url = reverse("clients:vat", args=[outcome.client.pk]) if outcome.client else ""
    level = DOUBT if outcome.level == importer.DOUBT else OK
    return Result(outcome.name, level, outcome.message, outcome.client, url,
                  outcome.title or outcome.message)  # fmt: skip


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
                      "enregistrée (tous les contrôles sont verts).", target, url,
                      f"Carte d'identité de {person.display_name}")  # fmt: skip
    return Result(name, DOUBT, f"Carte d'identité de {person.display_name} rangée, à "
                  f"confirmer : {document.review_reason or 'vérification à faire'}.", target,
                  url, f"Carte d'identité de {person.display_name}")  # fmt: skip


# --- Autres documents du SPF (D-084) ---------------------------------------------------------


def _spf_document(
    upload: UploadedFile[bytes], content_type: str, clients: QuerySet[Client], user: User,
    text: str,
) -> Result | None:  # fmt: skip
    from apps.core.models import CabinetSettings

    from . import spf_docs

    found = spf_docs.identify(text, clients, CabinetSettings.current().enterprise_number)
    if found is None:
        return None
    label = spf_docs.title(found)
    if len(found.clients) != 1:
        reason = (f"{label} reconnu, mais "
                  + ("aucun dossier ne correspond" if not found.clients
                     else "plusieurs dossiers correspondent"))  # fmt: skip
        return to_inbox(upload, content_type, user, reason)
    client = found.clients[0]
    cases = {c.slug: c for c in dossier.document_cases_for(client)}
    if found.kind.case in cases:
        documents.store(client, upload, title=label, case=found.kind.case,
                        doc_type=found.kind.doc_type, user=user)  # fmt: skip
        url = dossier.case_url(client.pk, cases[found.kind.case])
        return Result(upload.name or "document", OK, f"{label} rangé dans {client.display_name}.",
                      client, url, label)  # fmt: skip
    place = spf_docs.folder(found, client)
    if not place:
        what = "une personne physique" if client.is_person else "une société"
        return to_inbox(upload, content_type, user, f"{label} reconnu, mais le dossier est {what}")
    document = documents.store(client, upload, title=label, folder=place, user=user)
    url = dossier.folder_url(client.pk, place)
    ticked = ""
    if found.kind.deposit and found.year:
        from apps.closing import deposits  # la case de l'onglet Clôture se coche (D-114)

        end_year = found.year + found.kind.year_offset
        year = deposits.document_found(client, found.kind.deposit, end_year, document, user)
        if year is not None:
            box = deposits.Kind(found.kind.deposit).label
            done = "à vérifier" if found.kind.deposit == deposits.Kind.IPP_AER else "cochée"
            ticked = f" Case « {box} » {year.label} {done}."
            url = reverse("clients:closing", args=[client.pk])
    if found.kind.action:
        document.review_needed = True
        document.review_reason = "Courrier du SPF qui demande une réponse"
        document.save(update_fields=["review_needed", "review_reason"])
        return Result(upload.name or "document", DOUBT, f"{label} rangé dans {client.display_name}"
                      " : il demande une réponse, à traiter.", client, url, label)  # fmt: skip
    message = f"{label} rangé dans {client.display_name}.{ticked}"
    return Result(upload.name or "document", OK, message, client, url, label)


def _cabinet_invoice(
    upload: UploadedFile[bytes], content_type: str, clients: QuerySet[Client], user: User,
    text: str,
) -> Result | None:  # fmt: skip
    from apps.core.models import CabinetSettings

    from . import invoices

    # Seulement ce que le cabinet a encodé (jamais le nom par défaut « Cabinet »).
    cabinet = CabinetSettings.current()
    found = invoices.recognise(text, clients, cabinet.name, cabinet.enterprise_number)
    if found is None:
        return None
    if found.reason:
        return to_inbox(upload, content_type, user, f"{found.title} du cabinet reconnue, mais "
                        f"{found.reason}")  # fmt: skip
    client = found.clients[0]
    documents.store(client, upload, title=found.title, folder=invoices.FOLDER, user=user)
    return Result(upload.name or "document", OK, f"{found.title} rangée dans "
                  f"{client.display_name}.", client,
                  dossier.folder_url(client.pk, invoices.FOLDER), found.title)  # fmt: skip


def _xbrl_document(
    upload: UploadedFile[bytes], content_type: str, clients: QuerySet[Client], user: User
) -> Result | None:
    """Comptes annuels XBRL (BNB) ou déclaration Biztax → le bon dossier (D-098)."""
    from . import xbrl

    filing = xbrl.read(_content(upload))
    if filing is None:
        return None
    label = filing.title
    client = clients.filter(enterprise_number=filing.enterprise_number).first()
    if client is None:
        return to_inbox(upload, content_type, user, f"{label} reconnu, mais aucun dossier "
                        "ne correspond")  # fmt: skip
    place = dossier.ACCOUNTS_FOLDER if filing.kind == xbrl.ACCOUNTS else "isoc"
    if client.is_person:
        return to_inbox(upload, content_type, user,
                        f"{label} reconnu, mais le dossier est une personne physique")  # fmt: skip
    stored = documents.store(client, upload, title=label, folder=place, user=user)
    from apps.closing import deposits  # la case BNB / ISOC de l'exercice se coche (D-113)

    kind = deposits.Kind.BNB if filing.kind == xbrl.ACCOUNTS else deposits.Kind.ISOC
    deposits.xbrl_received(client, kind, filing.end, filing.assessment_year, stored, user)
    return Result(upload.name or "document", OK, f"{label} rangé dans {client.display_name}.",
                  client, dossier.folder_url(client.pk, place), label)  # fmt: skip


# --- Point d'entrée --------------------------------------------------------------------------


def duplicate_of(content: bytes, clients: QuerySet[Client]) -> Document | None:
    """Document déjà rangé avec exactement le même contenu (même empreinte SHA-256), parmi
    les dossiers visibles. Un fichier seulement ressemblant n'est jamais un doublon."""
    from django.db.models import Q

    digest = hashlib.sha256(content).hexdigest()
    return (
        Document.objects.filter(client__in=clients)
        .filter(Q(sha256=digest) | Q(source_hashes__contains=[digest]))
        .select_related("client")
        .order_by("-uploaded_at")
        .first()
    )


def hold_duplicate(
    upload: UploadedFile[bytes], content_type: str, user: User, existing: Document,
    intended: dict[str, Any] | None = None,
) -> Result:  # fmt: skip
    """Doublon : rien n'est rangé ni supprimé ; le fichier attend la décision (D-099).
    `intended` : l'endroit choisi dans l'onglet Documents, utilisé si on confirme (D-103)."""
    item = _keep(upload, content_type, user, "Déjà dans l'outil : à comparer", existing,
                 intended)  # fmt: skip
    return Result(item.original_name, DUPLICATE,
                  f"Déjà dans {existing.client.display_name} : à comparer",
                  url=reverse("depot:duplicate", args=[item.pk]), title=item.original_name,
                  where=existing.client.display_name)  # fmt: skip


def receive(
    uploads: Sequence[UploadedFile[bytes]], *, clients: QuerySet[Client], user: User,
    allow_duplicates: bool = False,
) -> list[Result]:  # fmt: skip
    results: list[Result] = []
    accepted: list[tuple[UploadedFile[bytes], str]] = []
    for upload in uploads:
        try:
            accepted.append((upload, _check(upload)))
        except ValidationError as error:
            results.append(Result(upload.name or "fichier", ERROR, " ".join(error.messages)))
    classified: list[tuple[intervat.Declaration, VatFiling]] = []

    def held(upload: UploadedFile[bytes], content_type: str) -> bool:
        if allow_duplicates:
            return False
        existing = duplicate_of(_content(upload), clients)
        if existing is None:
            return False
        results.append(hold_duplicate(upload, content_type, user, existing))
        return True

    # Les XML d'abord : un PDF déposé avec son XML le rejoint.
    for upload, content_type in accepted:
        if content_type != XML or held(upload, content_type):
            continue
        official = _xbrl_document(upload, content_type, clients, user)
        if official is not None:
            results.append(official)
            continue
        outcome = importer.import_xml(upload, clients, user, classified)
        if outcome.level == importer.ERROR:
            results.append(to_inbox(upload, content_type, user, outcome.message))
        else:
            results.append(_from_vat(outcome))
    for upload, content_type in accepted:
        if content_type == XML or held(upload, content_type):
            continue
        if content_type == PDF:
            from . import spf_docs

            text = spf_docs.text_of(_content(upload))
            # Documents du SPF sûrs (avertissement-extrait de rôle, Biztax…) avant la TVA :
            # un avertissement ISOC peut aussi contenir les mots « TVA » et « déclaration ».
            spf = _spf_document(upload, content_type, clients, user, text)
            if spf is not None:
                results.append(spf)
                continue
            # Facture émise par le cabinet : rangée chez le client (D-105).
            invoice = _cabinet_invoice(upload, content_type, clients, user, text)
            if invoice is not None:
                results.append(invoice)
                continue
            clues = intervat.read_pdf(_content(upload))
            if clues.looks_like_vat:
                outcome = importer.import_pdf(upload, clients, user, classified, clues)
                if outcome.level != importer.ERROR:
                    results.append(_from_vat(outcome))
                    continue
        # Un PDF plein de texte n'est pas une photo de carte : pas de lecture (lente) de carte
        # (grand test : l'extrait UBO tournait longtemps avant d'arriver « À classer »).
        looks_like_card = content_type in IMAGES or (
            content_type == PDF and (len(text.strip()) < 300 or "IDBEL" in text.upper())
        )
        if looks_like_card:
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
        (f"folder:{slug}", f"Archives › {s.label}") for slug, s in dossier.folders_for(client)
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


def confirm_duplicate(item: InboxItem, *, clients: QuerySet[Client], user: User) -> list[Result]:
    """« Confirmer l'import » : le fichier est traité comme un dépôt normal, doublon accepté.
    S'il n'est pas reconnu, il rejoint le document identique (même dossier, même place) au
    lieu de repartir dans « À classer »."""
    with item.file.open("rb") as handle:
        content = handle.read()
    existing = item.duplicate_of
    if existing is not None and not clients.filter(pk=existing.client_id).exists():
        existing = None
    upload = SimpleUploadedFile(item.original_name, content, item.content_type)
    target = item.intended or {}
    client = clients.filter(pk=target.get("client") or 0).first() if target else None
    if client is not None:
        # Ajouté dans une case précise : rangé là, comme prévu.
        person = Client.objects.filter(pk=target.get("person") or 0).first()
        document = documents.store(
            client, upload, title=target.get("title") or item.original_name,
            case=target.get("case", ""), folder=target.get("folder", ""), person=person,
            user=user, doc_type=target.get("doc_type", ""),
        )  # fmt: skip
        discard(item)
        return [Result(item.original_name, OK, f"{document.title} rangé dans "
                       f"{client.display_name}.", client, "", document.title)]  # fmt: skip
    if existing is None:
        results = receive([upload], clients=clients, user=user, allow_duplicates=True)
    else:
        with transaction.atomic():
            sid = transaction.savepoint_create()
            results = receive([upload], clients=clients, user=user, allow_duplicates=True)
            if [r.level for r in results] == [INBOX]:
                transaction.savepoint_rollback(sid)  # pas reconnu : on annule « À classer »
                results = [_beside(existing, item, content, user)]
    discard(item)
    return results


def _beside(existing: Document, item: InboxItem, content: bytes, user: User) -> Result:
    upload = SimpleUploadedFile(item.original_name, content, item.content_type)
    client = existing.client
    case, folder = existing.case, existing.folder
    if not case and not folder:
        folder = "administratif"
    document = documents.store(
        client, upload, title=existing.title, case=case, folder=folder,
        person=existing.person, user=user, doc_type=existing.doc_type,
    )  # fmt: skip
    cases = {c.slug: c for c in dossier.document_cases_for(client)}
    url = (dossier.case_url(client.pk, cases[case]) if case in cases
           else dossier.folder_url(client.pk, folder))  # fmt: skip
    return Result(item.original_name, OK, f"{document.title} rangé dans {client.display_name}.",
                  client, url, document.title)  # fmt: skip


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
