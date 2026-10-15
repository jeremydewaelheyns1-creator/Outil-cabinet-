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
)
ACCEPTED = "PDF, JPG, PNG, Word (.docx) ou Excel (.xlsx)"


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
REPLACED_GO_TO = {"pieces-identite": "administratif", "lettre-de-mission": "legal"}


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
    with transaction.atomic():
        if case in REPLACED_GO_TO:
            _archive_replaced(client, case, person)
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


def _archive_replaced(client: Client, case: str, person: Client | None) -> None:
    current = Document.objects.filter(client=client, case=case, archived_at__isnull=True)
    if case == "pieces-identite":
        current = current.filter(person=person)
    current.update(case="", folder=REPLACED_GO_TO[case], archived_at=timezone.now())


def current_documents(client: Client, case: str) -> list[Document]:
    return list(
        Document.objects.filter(client=client, case=case, archived_at__isnull=True)
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


def _title(kind: str, person: Client | None, label: str) -> str:
    if label.strip():
        return label.strip()[:200]
    base = DocumentRequest.Kind(kind).label
    if kind == DocumentRequest.Kind.IDENTITY_CARD and person is not None:
        return f"{base} de {person.display_name}"
    return base


def _email_body(request: DocumentRequest, reminder: bool) -> str:
    """Message volontairement neutre : aucune donnée sensible, aucune pièce jointe."""
    opening = (
        "Sauf erreur de notre part, nous n'avons pas encore reçu le document ci-dessous."
        if reminder
        else "Dans le cadre de notre mission, pourriez-vous nous transmettre le document "
        "ci-dessous ?"
    )
    return (
        f"Bonjour,\n\n{opening}\n\n— {request.title}\n\n"
        "Il vous suffit de répondre à ce message en joignant le document.\n\n"
        f"Référence : {request.reference}\n\n"
        f"Cordialement,\n{settings.CABINET_NAME}"
    )


def _prepare_email(request: DocumentRequest, kind: str) -> OutgoingEmail:
    reminder = kind == OutgoingEmail.Kind.REMINDER
    prefix = "Rappel : " if reminder else ""
    return OutgoingEmail.objects.create(
        request=request,
        kind=kind,
        to=request.recipient,
        subject=f"{prefix}{request.title} [réf. {request.reference}]",
        body=_email_body(request, reminder),
    )


def create_request(
    client: Client,
    kind: str,
    *,
    person: Client | None = None,
    label: str = "",
    user: User | None = None,
) -> DocumentRequest:
    with transaction.atomic():
        request = DocumentRequest.objects.create(
            client=client,
            kind=kind,
            person=person,
            title=_title(kind, person, label),
            recipient=_recipient(client),
            created_by=user,
            next_reminder_on=timezone.localdate() + timedelta(days=settings.REQUEST_REMINDER_DAYS),
        )
        _prepare_email(request, OutgoingEmail.Kind.REQUEST)
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
        )
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
            _prepare_email(request, OutgoingEmail.Kind.REMINDER)
            request.reminders_sent += 1
            request.next_reminder_on = today + timedelta(days=settings.REQUEST_REMINDER_DAYS)
            request.save(update_fields=["reminders_sent", "next_reminder_on"])
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
