"""Ranger les documents, demander des pièces au client, relancer, réceptionner (D-034).

Sécurité :
- seuls quelques formats sont acceptés, reconnus par leur contenu (pas par leur nom) ;
- taille limitée ; empreinte SHA-256 conservée (preuve d'intégrité) ;
- le fichier est stocké sous un nom aléatoire dans l'espace privé `documents` ;
- les e-mails ne contiennent ni pièce jointe ni donnée sensible : l'objet de la demande et une
  référence, rien d'autre.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import date, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.clients.models import Client, ContactPoint, Relation
from apps.core import events
from apps.core.models import User

from . import types
from .models import Document, DocumentRequest, OutgoingEmail


@dataclass(frozen=True)
class FileType:
    content_type: str
    extensions: tuple[str, ...]
    magic: tuple[bytes, ...]
    inline: bool  # affichable dans le navigateur (sinon : téléchargement)


FILE_TYPES = (
    FileType("application/pdf", (".pdf",), (b"%PDF-",), True),
    FileType("image/jpeg", (".jpg", ".jpeg"), (b"\xff\xd8\xff",), True),
    FileType("image/png", (".png",), (b"\x89PNG\r\n\x1a\n",), True),
    FileType(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        (".docx",),
        (b"PK\x03\x04",),
        False,
    ),
    FileType(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        (".xlsx",),
        (b"PK\x03\x04",),
        False,
    ),
    # Fichiers XML d'Intervat (déclarations TVA, listings) : téléchargés, jamais affichés.
    FileType("application/xml", (".xml",), (b"<?xml", b"\xef\xbb\xbf<?xml"), False),
)
ACCEPTED = "PDF, JPG, PNG, Word (.docx), Excel (.xlsx) ou XML"


def detect_type(upload: UploadedFile[bytes]) -> FileType:
    """Type réel du fichier, d'après ses premiers octets ET son extension."""
    name = (upload.name or "").lower()
    upload.seek(0)
    head = upload.read(16)
    upload.seek(0)
    for file_type in FILE_TYPES:
        if name.endswith(file_type.extensions) and head.startswith(file_type.magic):
            return file_type
    raise ValidationError(f"Format non accepté. Formats acceptés : {ACCEPTED}.")


def inline_allowed(document: Document) -> bool:
    return any(t.inline and t.content_type == document.content_type for t in FILE_TYPES)


# --- Où ranger --------------------------------------------------------------------------------

# Destination d'une pièce reçue en réponse à une demande : case en cours ou dossier d'archives.
DESTINATIONS: dict[str, tuple[str, str]] = {
    DocumentRequest.Kind.IDENTITY_CARD: ("pieces-identite", ""),
    DocumentRequest.Kind.UBO: ("ubo", ""),
    DocumentRequest.Kind.SIGNATURE: ("", "legal"),
    DocumentRequest.Kind.OTHER: ("", "administratif"),
}
# Quand une pièce en remplace une autre, l'ancienne part dans ce dossier d'archives.


def store(
    client: Client,
    upload: UploadedFile[bytes],
    *,
    title: str,
    case: str = "",
    folder: str = "",
    person: Client | None = None,
    request: DocumentRequest | None = None,
    user: User | None = None,
    doc_type: str = "",
    expires_on: date | None = None,
) -> Document:
    """Vérifie et enregistre un document (dans une case, ou directement aux archives)."""
    if not case and not folder:
        raise ValueError("Un document doit être rangé dans une case ou un dossier.")
    if upload.size is None or upload.size == 0:
        raise ValidationError("Le fichier est vide.")
    if upload.size > settings.DOCUMENT_MAX_BYTES:
        limit = settings.DOCUMENT_MAX_BYTES // (1024 * 1024)
        raise ValidationError(f"Fichier trop lourd (maximum {limit} Mo).")
    file_type = detect_type(upload)
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    if case == "pieces-identite":
        doc_type = doc_type or types.CARD
    with transaction.atomic():
        if case:
            archive_replaced(client, case, doc_type, person)
        document = Document(
            client=client,
            title=title.strip()[:200] or "Document",
            case=case,
            folder=folder,
            person=person,
            request=request,
            source=Document.Source.REQUEST if request else Document.Source.UPLOAD,
            original_name=(upload.name or "document")[-255:],
            content_type=file_type.content_type,
            size=upload.size,
            sha256=digest.hexdigest(),
            uploaded_by=user,
            archived_at=timezone.now() if folder and not case else None,
            doc_type=doc_type,
            expires_on=expires_on,
        )
        document.file.save("document", upload, save=False)
        document.save()
    events.emit(
        "document.added",
        subject=client,
        actor=user,
        payload={"document": str(document.pk), "case": case, "folder": folder},
    )
    return document


def archive_replaced(client: Client, case: str, doc_type: str, person: Client | None) -> None:
    """Le nouveau document remplace l'ancien du même type (et de la même personne) : l'ancien
    part aux archives."""
    if doc_type == types.CARD:
        folder = "administratif"
    elif doc_type in types.BY_SLUG and doc_type != "autre":
        folder = types.BY_SLUG[doc_type].archive_folder
    else:
        return
    current = Document.objects.filter(
        client=client,
        case=case,
        doc_type=doc_type,
        archived_at__isnull=True,
        state=Document.State.FINAL,
    )
    if doc_type == types.CARD or (doc_type in types.BY_SLUG and types.BY_SLUG[doc_type].per):
        current = current.filter(person=person)
    current.update(case="", folder=folder, archived_at=timezone.now())


def current_documents(client: Client, case: str) -> list[Document]:
    return list(
        Document.objects.filter(
            client=client, case=case, archived_at__isnull=True, state=Document.State.FINAL
        )
        .select_related("person", "uploaded_by")
        .order_by("-uploaded_at")
    )


def archived_documents(client: Client, folder: str) -> list[Document]:
    return list(
        Document.objects.filter(client=client, folder=folder)
        .select_related("person", "uploaded_by")
        .order_by("-uploaded_at")
    )


# --- Demandes « À recevoir » ----------------------------------------------------------------


def people_concerned(client: Client) -> list[Client]:
    """Personnes physiques dont on peut demander une pièce : le client lui-même s'il est une
    personne, sinon ses mandataires et actionnaires en cours."""
    if client.is_person:
        return [client]
    ids = (
        Relation.objects.current()
        .filter(entity=client, person__kind=Client.Kind.PERSON)
        .values_list("person_id", flat=True)
    )
    return list(Client.objects.filter(pk__in=ids).order_by("name", "first_name"))


def _recipient(client: Client) -> str:
    contacts = client.contacts.filter(kind=ContactPoint.Kind.EMAIL)
    primary = contacts.filter(is_primary=True).first() or contacts.first()
    return primary.value if primary else ""


def _title(kind: str, person: Client | None, label: str, doc_type: str = "") -> str:
    if label.strip():
        return label.strip()[:200]
    if doc_type in types.BY_SLUG:
        base = types.BY_SLUG[doc_type].label
        return f"{base} — {person.display_name}" if person is not None else base
    base = DocumentRequest.Kind(kind).label
    if kind == DocumentRequest.Kind.IDENTITY_CARD and person is not None:
        return f"{base} de {person.display_name}"
    return base


# --- Lien sécurisé de dépôt (D-046) ----------------------------------------------------------


def _link_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def open_link(request: DocumentRequest) -> None:
    """Crée (ou prolonge) le lien personnel de dépôt de cette demande."""
    from apps.outlook.graph import encrypt

    expires = timezone.now() + timedelta(days=settings.REQUEST_LINK_DAYS)
    if not request.link_hash:
        token = secrets.token_urlsafe(32)
        request.link_hash, request.link_token = _link_hash(token), encrypt(token)
    request.link_expires_at = max(expires, request.link_expires_at or expires)
    request.save(update_fields=["link_hash", "link_token", "link_expires_at"])


def upload_url(request: DocumentRequest) -> str:
    from django.urls import reverse

    from apps.outlook.graph import decrypt

    token = decrypt(request.link_token)
    base = str(settings.SITE_URL).rstrip("/")
    return base + reverse("depot_client:page", args=[token])


def request_for_link(token: str) -> DocumentRequest | None:
    """La demande de ce lien, seulement s'il est encore valable (sinon : rien, sans détail)."""
    if not token or len(token) > 100:
        return None
    request = (
        DocumentRequest.objects.filter(link_hash=_link_hash(token))
        .select_related("client", "person")
        .first()
    )
    if (
        request is None
        or request.status != DocumentRequest.Status.PENDING
        or request.link_expires_at is None
        or request.link_expires_at < timezone.now()
        or request.link_attempts >= settings.REQUEST_LINK_MAX_ATTEMPTS
    ):
        return None
    return request


def _email_body(request: DocumentRequest, reminder: bool, sender: User | None) -> str:
    """Message clair et neutre : aucune donnée sensible, aucune pièce jointe (D-045)."""
    greeting = request.client.greeting
    who = request.person.display_name if request.person is not None else ""
    link = ""
    if request.link_token:
        until = timezone.localtime(request.link_expires_at) if request.link_expires_at else None
        valid = f" (valable jusqu'au {until:%d/%m/%Y})" if until else ""
        link = f"{upload_url(request)}{valid}"
    if request.kind == DocumentRequest.Kind.IDENTITY_CARD:
        intro = (
            f"Petit rappel : nous n'avons pas encore reçu la carte d'identité de {who}."
            if reminder
            else "Dans le cadre de nos obligations légales (loi anti-blanchiment du 18 septembre "
            f"2017), nous devons conserver une copie à jour de la carte d'identité de {who}."
        )
        action = (
            "Pour nous la transmettre en toute sécurité, utilisez ce lien personnel"
            f"{' ' if link else ''}: {link}\n\nIl suffit d'y déposer une photo nette du recto et "
            "du verso de la carte. Pour protéger vos données, merci de ne pas l'envoyer par "
            "e-mail."
        )
    elif request.kind == DocumentRequest.Kind.SIGNATURE:
        intro = (
            f"Petit rappel : le document « {request.title} » attend encore votre signature."
            if reminder
            else f"Nous avons préparé le document « {request.title} ». Il est déjà signé par "
            "notre cabinet et n'attend plus que votre signature."
        )
        action = (
            "Vous pourrez le consulter et le signer via ce lien sécurisé : "
            "[lien de signature — disponible quand la signature en ligne sera branchée]"
        )
    else:
        intro = (
            f"Petit rappel : nous n'avons pas encore reçu le document « {request.title} »."
            if reminder
            else f"Pour la bonne tenue de votre dossier, pourriez-vous nous transmettre le "
            f"document suivant : « {request.title} » ?"
        )
        action = (
            f"Vous pouvez le déposer en toute sécurité via ce lien personnel : {link}"
            if link
            else "Il vous suffit de répondre à cet e-mail en le joignant."
        )
    signature = [sender.get_full_name()] if sender is not None and sender.get_full_name() else []
    lines = [greeting, "", intro, "", action, "", "Merci d'avance pour votre aide.", "",
             "Bien à vous,", *signature, settings.CABINET_NAME, "",
             f"Référence de la demande : {request.reference}"]  # fmt: skip
    return "\n".join(lines)


def _prepare_email(request: DocumentRequest, kind: str) -> OutgoingEmail:
    from .mailing import sender_for

    reminder = kind == OutgoingEmail.Kind.REMINDER
    prefix = "Rappel : " if reminder else ""
    sender = sender_for(request.client, request.created_by)
    return OutgoingEmail.objects.create(
        request=request,
        kind=kind,
        to=request.recipient,
        subject=f"{prefix}{request.title} [réf. {request.reference}]",
        body=_email_body(request, reminder, sender),
    )


def _deliver(email: OutgoingEmail, user: User | None) -> None:
    """Envoi réel, après l'enregistrement (un refus de Microsoft n'annule pas la demande)."""
    from .mailing import deliver

    deliver(email, user)


def create_request(
    client: Client,
    kind: str,
    *,
    person: Client | None = None,
    label: str = "",
    user: User | None = None,
    doc_type: str = "",
) -> DocumentRequest:
    with transaction.atomic():
        request = DocumentRequest.objects.create(
            client=client,
            kind=kind,
            person=person,
            doc_type=doc_type,
            title=_title(kind, person, label, doc_type),
            recipient=_recipient(client),
            created_by=user,
            next_reminder_on=timezone.localdate() + timedelta(days=settings.REQUEST_REMINDER_DAYS),
        )
        if kind != DocumentRequest.Kind.SIGNATURE:
            open_link(request)
        email = _prepare_email(request, OutgoingEmail.Kind.REQUEST)
    _deliver(email, user)
    events.emit(
        "document_request.created",
        subject=client,
        actor=user,
        payload={"request": str(request.pk), "kind": kind},
    )
    return request


def receive(
    request: DocumentRequest, upload: UploadedFile[bytes], *, user: User | None = None
) -> Document:
    """La pièce demandée est arrivée : elle va dans sa case (ou aux archives)."""
    if request.status != DocumentRequest.Status.PENDING:
        raise ValidationError("Cette demande n'est plus en attente.")
    case, folder = DESTINATIONS.get(request.kind, ("", "administratif"))
    expected = types.BY_SLUG.get(request.doc_type)
    if expected is not None:
        case, folder = (expected.case, "") if expected.case else ("", expected.archive_folder)
    with transaction.atomic():
        document = store(
            request.client,
            upload,
            title=request.title,
            case=case,
            folder=folder,
            person=request.person,
            request=request,
            user=user,
            doc_type=request.doc_type,
        )
        # La version envoyée pour signature est gardée aux archives, comme preuve.
        for sent in request.documents.filter(state=Document.State.AWAITING_SIGNATURE):
            kind = types.BY_SLUG.get(sent.doc_type)
            sent.case, sent.folder = "", kind.archive_folder if kind else "administratif"
            sent.archived_at = timezone.now()
            sent.save(update_fields=["case", "folder", "archived_at"])
        request.status = DocumentRequest.Status.RECEIVED
        request.closed_at = timezone.now()
        request.next_reminder_on = None
        request.save(update_fields=["status", "closed_at", "next_reminder_on"])
    events.emit(
        "document_request.received",
        subject=request.client,
        actor=user,
        payload={"request": str(request.pk), "document": str(document.pk)},
    )
    return document


def cancel(request: DocumentRequest, *, user: User | None = None) -> None:
    if request.status != DocumentRequest.Status.PENDING:
        return
    request.status = DocumentRequest.Status.CANCELLED
    request.closed_at = timezone.now()
    request.next_reminder_on = None
    request.save(update_fields=["status", "closed_at", "next_reminder_on"])
    events.emit(
        "document_request.cancelled", subject=request.client, actor=user,
        payload={"request": str(request.pk)},
    )  # fmt: skip


def send_due_reminders(today: date | None = None) -> int:
    """Relances automatiques (passage quotidien de run_jobs). Idempotent pour une journée."""
    today = today or timezone.localdate()
    due = DocumentRequest.objects.filter(
        status=DocumentRequest.Status.PENDING,
        next_reminder_on__lte=today,
        reminders_sent__lt=settings.REQUEST_MAX_REMINDERS,
    )
    count = 0
    for request in due:
        with transaction.atomic():
            if request.link_hash:
                open_link(request)  # le lien reste le même, sa validité est prolongée
            email = _prepare_email(request, OutgoingEmail.Kind.REMINDER)
            request.reminders_sent += 1
            request.next_reminder_on = today + timedelta(days=settings.REQUEST_REMINDER_DAYS)
            request.save(update_fields=["reminders_sent", "next_reminder_on"])
        _deliver(email, None)
        count += 1
    return count


def overdue_requests(client: Client) -> list[DocumentRequest]:
    """Demandes restées sans réponse après toutes les relances."""
    today = timezone.localdate()
    return list(
        client.document_requests.filter(
            status=DocumentRequest.Status.PENDING,
            reminders_sent__gte=settings.REQUEST_MAX_REMINDERS,
        ).filter(Q(next_reminder_on__lte=today) | Q(next_reminder_on__isnull=True))
    )


def pending_requests(client: Client) -> list[DocumentRequest]:
    return list(
        client.document_requests.filter(status=DocumentRequest.Status.PENDING)
        .select_related("person")
        .prefetch_related("emails")
    )
