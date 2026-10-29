"""Signature en ligne d'un document par le client (D-048).

Le client reçoit un lien personnel (D-046). Il lit le document (pages affichées en images) et
le signe en dessinant sa signature. L'outil :
1. vérifie la signature dessinée (vraie image, pas vide, taille raisonnable) et la redessine
   (aucun contenu caché ne passe) ;
2. reporte ses réponses et sa signature dans le document (s'il a été produit par l'outil et
   que rien n'a changé depuis sa lecture, D-103) et ajoute une page « certificat de
   signature » : qui, quand, d'où, empreinte SHA-256 du document lu (gardé aux archives) ;
3. range le document signé à sa place (l'ancien part aux archives), clôture la demande,
   garde la preuve (`Signature`) et envoie une copie au client depuis la boîte Outlook.

Valeur juridique : signature électronique simple — admise en droit belge (livre 8 du Code
civil), appréciée par le juge ; la piste d'audit et l'empreinte la renforcent. Une signature
qualifiée (itsme, carte eID) pourra être ajoutée plus tard par un prestataire agréé.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
from typing import Any

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.utils import timezone

from apps.core import events
from apps.core.cabinet import cabinet_name

from . import types
from .models import Document, DocumentRequest, Signature

MAX_SIGNATURE_BYTES = 400 * 1024
PNG_PREFIX = "data:image/png;base64,"


def awaiting_document(request: DocumentRequest) -> Document | None:
    return request.documents.filter(state=Document.State.AWAITING_SIGNATURE).first()


def clean_signature(data_url: str) -> bytes:
    """La signature dessinée, vérifiée et redessinée en PNG propre."""
    from PIL import Image, UnidentifiedImageError

    if not data_url.startswith(PNG_PREFIX):
        raise ValidationError("Signature manquante : dessinez votre signature dans le cadre.")
    try:
        raw = base64.b64decode(data_url[len(PNG_PREFIX) :], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError("Signature illisible : recommencez.") from exc
    if len(raw) > MAX_SIGNATURE_BYTES:
        raise ValidationError("Signature trop lourde : recommencez.")
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValidationError("Signature illisible : recommencez.") from exc
    if image.width > 2000 or image.height > 1000:
        raise ValidationError("Signature illisible : recommencez.")
    flat = Image.new("RGB", image.size, "white")
    flat.paste(image.convert("RGBA"), mask=image.convert("RGBA").getchannel("A"))
    histogram = flat.convert("L").histogram()
    inked = sum(histogram[:128])  # nombre de points foncés
    if inked < 40:  # quelques points ne font pas une signature
        raise ValidationError("Signature trop courte : signez dans le cadre.")
    out = io.BytesIO()
    flat.save(out, format="PNG")
    return out.getvalue()


def answers_from(document: Document, posted: Any) -> dict[str, dict[str, Any]]:
    """Réponses du signataire aux questions du document (D-071), vérifiées.

    Pour chaque bénéficiaire : PEP oui / non (obligatoire) et lieu de naissance (obligatoire)."""
    answers: dict[str, dict[str, Any]] = {}
    for question in document.questions or []:
        key = str(question.get("person"))
        pep = posted.get(f"pep-{key}", "")
        place = " ".join(str(posted.get(f"lieu-{key}", "")).split())[:100]
        if pep not in {"oui", "non"} or len(place) < 2:
            raise ValidationError(
                "Répondez aux questions sur chaque bénéficiaire effectif (lieu de naissance et "
                "personne politiquement exposée)."
            )
        answers[key] = {"name": str(question.get("name", ""))[:150], "pep": pep == "oui",
                        "lieu": place}  # fmt: skip
    return answers


def _certificate(
    request: DocumentRequest, document: Document, *, signer_name: str, signer_role: str,
    signature_png: bytes, signed_at: object, ip: str | None, original_sha256: str,
    answers: dict[str, dict[str, Any]] | None = None, filled: bool = False,
) -> bytes:  # fmt: skip
    from weasyprint import HTML

    html = render_to_string(
        "documents/modeles/certificat_signature.html",
        {
            "cabinet": cabinet_name(),
            "title": document.title,
            "client": request.client.display_name,
            "reference": request.reference,
            "recipient": request.recipient,
            "signer_name": signer_name,
            "signer_role": signer_role,
            "signed_at": signed_at,
            "ip": ip,
            "original_sha256": original_sha256,
            "signature_uri": "data:image/png;base64," + base64.b64encode(signature_png).decode(),
            "answers": list((answers or {}).values()),
            "filled": filled,
        },
    )
    return bytes(HTML(string=html).write_pdf())


def _filled(
    document: Document, *, signer_name: str, signer_role: str, signature_png: bytes,
    signed_at: Any, answers: dict[str, dict[str, Any]] | None,
) -> bytes | None:  # fmt: skip
    """Le document tel que lu, avec les réponses et la signature du client reportées à leur
    place (D-103). Seulement pour un document produit par l'outil dont les données n'ont pas
    changé depuis (sinon il ne serait plus identique à ce que le client a lu) : on garde alors
    le document lu tel quel, les réponses restant sur le certificat."""
    from . import generation

    if not document.generated or document.doc_type not in generation.MODELS:
        return None
    day = timezone.localtime(document.uploaded_at).date()
    args = (document.client, document.doc_type, document.person, document.uploaded_by)
    with document.file.open("rb") as handle:
        read = handle.read()
    # Le même document, refait aujourd'hui sans signature, doit être mot pour mot celui lu.
    if _words(generation.render_pdf(*args, day=day)) != _words(read):
        return None
    signed = {
        "name": signer_name, "role": signer_role.strip()[:100], "at": signed_at,
        "signature_uri": "data:image/png;base64," + base64.b64encode(signature_png).decode(),
        "answers": answers or {},
    }  # fmt: skip
    return generation.render_pdf(*args, signed=signed, day=day)


def _words(content: bytes) -> list[str]:
    from pypdf import PdfReader

    return " ".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages
    ).split()


def _merge(original: bytes, certificate: bytes) -> bytes:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for source in (original, certificate):
        for page in PdfReader(io.BytesIO(source)).pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def sign(
    request: DocumentRequest,
    *,
    signer_name: str,
    signer_role: str,
    signature_data_url: str,
    ip: str | None,
    user_agent: str,
    answers: dict[str, dict[str, Any]] | None = None,
) -> Document:
    from .services import receive

    signer_name = signer_name.strip()[:150]
    if len(signer_name) < 3:
        raise ValidationError("Indiquez vos nom et prénom.")
    original_doc = awaiting_document(request)
    if original_doc is None:
        raise ValidationError("Ce document n'est plus disponible à la signature.")
    signature_png = clean_signature(signature_data_url)
    with original_doc.file.open("rb") as handle:
        original = handle.read()
    original_sha256 = hashlib.sha256(original).hexdigest()
    signed_at = timezone.localtime()
    filled = _filled(original_doc, signer_name=signer_name, signer_role=signer_role,
                     signature_png=signature_png, signed_at=signed_at, answers=answers)  # fmt: skip
    certificate = _certificate(
        request, original_doc, signer_name=signer_name, signer_role=signer_role.strip()[:100],
        signature_png=signature_png, signed_at=signed_at, ip=ip, original_sha256=original_sha256,
        answers=answers, filled=filled is not None,
    )  # fmt: skip
    merged = _merge(filled or original, certificate)
    name = f"{original_doc.doc_type or 'document'}-signe.pdf"
    upload = SimpleUploadedFile(name, merged, content_type="application/pdf")
    document = receive(request, upload)
    label = types.BY_SLUG[request.doc_type].label if request.doc_type in types.BY_SLUG else ""
    document.title = f"{label or original_doc.title} — signé le {signed_at:%d/%m/%Y}"[:200]
    document.data_fingerprint = original_doc.data_fingerprint  # mêmes données que l'original
    document.save(update_fields=["title", "data_fingerprint"])
    Signature.objects.create(
        request=request, document=document, signer_name=signer_name,
        signer_role=signer_role.strip()[:100], signed_at=signed_at, ip_address=ip,
        user_agent=user_agent[:255], original_sha256=original_sha256,
        signed_sha256=hashlib.sha256(merged).hexdigest(), answers=answers or {},
    )  # fmt: skip
    events.emit(
        "document.signed",
        subject=request.client,
        actor=None,
        payload={
            "document": str(document.pk),
            "demande": request.reference,
            "ppe_declaree": any(a.get("pep") for a in (answers or {}).values()),
        },
    )
    _send_copy(request, document, merged)
    return document


def person_answers(person: Any) -> dict[str, Any] | None:
    """Dernières réponses données pour cette personne dans une déclaration UBO signée en
    ligne (lieu de naissance, PEP), quel que soit le dossier (D-086)."""
    key = str(person.pk)
    for found in Signature.objects.filter(answers__has_key=key).order_by("-signed_at")[:1]:
        return dict(found.answers[key])
    return None


def latest_answers(client: Any) -> Signature | None:
    """Dernière déclaration UBO signée en ligne avec ses réponses (PEP, lieu de naissance)."""
    return (
        Signature.objects.filter(request__client=client, document__doc_type="declaration_ubo")
        .exclude(answers={})
        .order_by("-signed_at")
        .first()
    )


def _send_copy(request: DocumentRequest, document: Document, content: bytes) -> None:
    """Copie du document signé envoyée au client depuis la boîte de l'équipe du dossier."""
    from apps.outlook import graph

    from .mailing import archive_copy, sender_for

    if not request.recipient:
        return
    sender = sender_for(request.client, request.created_by)
    link = graph.mailbox_for(sender)
    if link is None:
        return
    subject = f"Votre document signé : {document.title}"
    body = "\n".join([
        request.client.greeting, "",
        "Merci pour votre signature. Vous trouverez en pièce jointe une copie du document "
        "signé, avec son certificat de signature.", "",
        "Bien à vous,", *([sender.get_full_name()] if sender and sender.get_full_name() else []),
        cabinet_name(),
    ])  # fmt: skip
    attachment = graph.Attachment(f"{document.title[:80]}.pdf".replace("/", "-"), content)
    try:
        graph.send(link, to=request.recipient, subject=subject, body=body,
                   attachments=[attachment])  # fmt: skip
    except graph.MailboxError:
        return
    archive_copy(
        request.client, sender=link.address, to=request.recipient, subject=subject, body=body,
        sent_at=timezone.now(), attachments=[attachment.name], user=sender, request=request,
    )  # fmt: skip
