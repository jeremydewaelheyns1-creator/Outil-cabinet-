"""Importer les fichiers d'Intervat : chaque fichier trouve seul son dossier et sa ligne (D-040).

- XML : certain (numéro de TVA + période lus dans le fichier) → classé directement, grille 71
  ou 72 reprise, case « Déposée » (ou « IC ») cochée. Annulable : il suffit de remettre la
  case dans son état précédent ; le fichier reste dans les archives TVA du dossier.
- PDF déposé avec son XML : rattaché à la même déclaration.
- PDF seul : dossier reconnu → rangé dans ses archives TVA et proposé « à confirmer » ;
  dossier non reconnu → rien n'est rangé (jamais de fichier dans un mauvais dossier).
- Un XML qui groupe plusieurs clients : montants repris, mais le fichier n'est rangé dans
  aucun dossier (chaque dossier montrerait les chiffres des autres clients).

Seuls les dossiers visibles par l'utilisateur sont cherchés : un fichier d'un dossier privé
qu'il ne voit pas est traité comme « dossier non reconnu ».
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db.models import QuerySet

from apps.clients.models import Client
from apps.core import events
from apps.core.models import User
from apps.documents import services as documents
from apps.documents.models import Document

from . import intervat
from .intervat import IC, KIND_LABELS, VAT, Declaration
from .models import Column, Status, VatFiling, VatPending
from .services import filing_for, period, set_status

OK = "ok"  # classé
SAME = "same"  # déjà importé
DOUBT = "doubt"  # rangé dans le dossier, période à confirmer
ERROR = "error"  # rien n'a été rangé


@dataclass
class Outcome:
    name: str
    level: str
    message: str
    client: Client | None = None
    filing: VatFiling | None = None


def _cap(text: str) -> str:
    """Majuscule au début sans toucher au reste (« déclaration TVA » → « Déclaration TVA »)."""
    return text[:1].upper() + text[1:]


def _read(upload: UploadedFile[bytes]) -> bytes:
    upload.seek(0)
    content = bytes(upload.read())
    upload.seek(0)
    return content


def _check(upload: UploadedFile[bytes]) -> str:
    """Contrôles communs (taille, format réel) ; renvoie le type du fichier."""
    if not upload.size or upload.size > settings.DOCUMENT_MAX_BYTES:
        raise ValidationError("Fichier vide ou trop lourd.")
    return documents.detect_type(upload).content_type


def _store(client: Client, upload: UploadedFile[bytes], title: str, user: User | None) -> Document:
    return documents.store(client, upload, title=title, folder="tva", user=user)


def _apply(filing: VatFiling, declaration: Declaration, user: User | None) -> None:
    if declaration.kind == VAT:
        grids = declaration.grids
        filing.grid_71, filing.grid_72 = grids.get("71"), grids.get("72")
        if filing.grid_71 is None and filing.grid_72 is None:
            filing.grid_71 = Decimal("0.00")
        filing.save(update_fields=["grid_71", "grid_72"])
        set_status(filing, Column.FILED, Status.DONE, user=user)
    else:
        set_status(filing, Column.IC, Status.DONE, user=user)
    events.emit(
        "vat.return_imported",
        subject=filing.client,
        actor=user,
        payload={"periode": filing.period_key, "sorte": declaration.kind},
    )


def import_xml(
    upload: UploadedFile[bytes],
    clients: QuerySet[Client],
    user: User | None,
    classified: list[tuple[Declaration, VatFiling]],
) -> Outcome:
    name = upload.name or "fichier.xml"
    content = _read(upload)
    try:
        declarations = intervat.parse_xml(content)
    except intervat.IntervatError as error:
        return Outcome(name, ERROR, str(error))
    found: list[tuple[Declaration, VatFiling]] = []
    for declaration in declarations:
        client = clients.filter(enterprise_number=declaration.enterprise_number).first()
        if client is None:
            continue
        p = period(declaration.year, month=declaration.month, quarter=declaration.quarter)
        found.append((declaration, filing_for(client, p)))
    if not found:
        return Outcome(name, ERROR, "Aucun dossier reconnu : rien n'a été rangé.")
    if len(declarations) > 1:
        for declaration, filing in found:
            _apply(filing, declaration, user)
        missing = len(declarations) - len(found)
        return Outcome(
            name,
            OK,
            f"Fichier groupé : {len(found)} déclaration(s) reprise(s) dans la grille"
            + (f", {missing} sans dossier reconnu" if missing else "")
            + ". Le fichier n'est rangé dans aucun dossier (il contient plusieurs clients).",
        )
    declaration, filing = found[0]
    classified.append((declaration, filing))
    label = KIND_LABELS[declaration.kind]
    current = filing.xml if declaration.kind == VAT else filing.ic_xml
    digest = hashlib.sha256(content).hexdigest()
    if current is not None and current.sha256 == digest:
        return Outcome(name, SAME, f"{label} {filing.short_label} déjà importé(e).", filing.client,
                       filing)  # fmt: skip
    document = _store(filing.client, upload, f"{_cap(label)} {filing.period_label} (XML)",
                      user)  # fmt: skip
    if declaration.kind == VAT:
        filing.xml = document
    else:
        filing.ic_xml = document
    filing.save(update_fields=["xml", "ic_xml"])
    _apply(filing, declaration, user)
    replaced = " (remplace la version importée avant)" if current is not None else ""
    return Outcome(
        name, OK, f"{_cap(label)} {filing.short_label} classé(e){replaced}.",
        filing.client, filing,
    )  # fmt: skip


def attach_pdf(filing: VatFiling, document: Document, kind: str, user: User | None) -> None:
    if kind == VAT:
        filing.pdf = document
    else:
        filing.ic_pdf = document
    filing.save(update_fields=["pdf", "ic_pdf"])
    column = Column.FILED if kind == VAT else Column.IC
    if not filing.cells.filter(column=column, status=Status.DONE).exists():
        set_status(filing, column, Status.DONE, user=user)


def import_pdf(
    upload: UploadedFile[bytes],
    clients: QuerySet[Client],
    user: User | None,
    classified: list[tuple[Declaration, VatFiling]],
    clues: intervat.PdfClues | None = None,
) -> Outcome:
    name = upload.name or "fichier.pdf"
    clues = clues or intervat.read_pdf(_read(upload))
    wanted = (clues.year, clues.month, clues.quarter)
    # 1. Il accompagne un XML du même envoi (même client, même sorte, même période si lue).
    partners = [
        (d, f)
        for d, f in classified
        if d.kind == clues.kind
        and d.enterprise_number in clues.numbers
        and (clues.year is None or wanted == (d.year, d.month, d.quarter))
    ]
    label = KIND_LABELS[clues.kind]
    if len(partners) == 1:
        _, filing = partners[0]
        document = _store(filing.client, upload,
                          f"{_cap(label)} {filing.period_label} (PDF)", user)  # fmt: skip
        attach_pdf(filing, document, clues.kind, user)
        return Outcome(name, OK, f"PDF joint : {label} {filing.short_label}.", filing.client,
                       filing)  # fmt: skip
    # 2. Seul : on range dans le dossier reconnu, la période reste à confirmer.
    matched = list(clients.filter(enterprise_number__in=clues.numbers)[:2])
    if len(matched) != 1:
        return Outcome(
            name, ERROR,
            "Dossier non reconnu dans ce PDF : rien n'a été rangé. Importe-le avec son XML.",
        )  # fmt: skip
    client = matched[0]
    key = ""
    if clues.year is not None:
        key = period(clues.year, month=clues.month, quarter=clues.quarter).key
        # La période lue correspond à un XML déjà importé pour ce dossier : deux preuves.
        known = VatFiling.objects.filter(client=client, period_key=key).first()
        if known is not None:
            ids = (known.xml_id, known.pdf_id) if clues.kind == VAT else (
                known.ic_xml_id, known.ic_pdf_id)  # fmt: skip
            if ids[0] and not ids[1]:
                title = f"{_cap(label)} {known.period_label} (PDF)"
                attach_pdf(known, _store(client, upload, title, user), clues.kind, user)
                return Outcome(name, OK, f"PDF joint : {label} {known.short_label}.", client,
                               known)  # fmt: skip
    document = _store(client, upload, f"{_cap(label)} (PDF, à confirmer)", user)
    VatPending.objects.create(document=document, kind=clues.kind, period_key=key)
    return Outcome(name, DOUBT, "PDF rangé dans le dossier : période à confirmer.", client)


def import_files(
    uploads: Sequence[UploadedFile[bytes]], *, clients: QuerySet[Client], user: User | None
) -> list[Outcome]:
    outcomes: list[Outcome] = []
    xmls, pdfs = [], []
    for upload in uploads:
        try:
            content_type = _check(upload)
        except ValidationError as error:
            outcomes.append(Outcome(upload.name or "fichier", ERROR, " ".join(error.messages)))
            continue
        if content_type == "application/xml":
            xmls.append(upload)
        elif content_type == "application/pdf":
            pdfs.append(upload)
        else:
            outcomes.append(Outcome(upload.name or "fichier", ERROR, "Seuls le XML et le PDF "
                                    "d'Intervat sont acceptés ici."))  # fmt: skip
    classified: list[tuple[Declaration, VatFiling]] = []
    for upload in xmls:
        outcomes.append(import_xml(upload, clients, user, classified))
    for upload in pdfs:
        outcomes.append(import_pdf(upload, clients, user, classified))
    return outcomes


def confirm(pending: VatPending, filing: VatFiling, kind: str, user: User | None) -> None:
    """Le gestionnaire confirme la période d'un PDF reçu seul."""
    if kind not in (VAT, IC) or filing.client_id != pending.document.client_id:
        raise ValueError("Déclaration invalide.")
    document = pending.document
    document.title = f"{_cap(KIND_LABELS[kind])} {filing.period_label} (PDF)"
    document.save(update_fields=["title"])
    attach_pdf(filing, document, kind, user)
    pending.delete()
