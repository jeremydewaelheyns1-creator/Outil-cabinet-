"""Relève des boîtes Outlook (D-060) : passage de `run_jobs` toutes les 5 minutes.

Pour chaque employé qui a activé la lecture : nouveaux e-mails de « Boîte de réception » et
d'« Éléments envoyés » depuis le dernier passage (jamais avant l'activation). Chaque e-mail
est copié (texte simple), ses pièces jointes aussi (sauf images intégrées), puis l'outil
suggère un dossier. Un e-mail retiré comme privé n'est jamais recopié.
Rien du contenu n'est écrit dans les journaux.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings
from django.contrib.postgres.search import SearchVector
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.models import Q, Value
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.clients.models import Client
from apps.documents.services import detect_type
from apps.outlook import graph
from apps.outlook.models import MailboxLink

from . import classify, recognize
from .models import Awaiting, MailAttachment, MailExclusion, MailMessage

logger = logging.getLogger(__name__)

FOLDERS = (
    ("inbox", MailMessage.Folder.INBOX, "receivedDateTime", "inbox_cursor"),
    ("sentitems", MailMessage.Folder.SENT, "sentDateTime", "sent_cursor"),
)
SELECT = (
    "id,conversationId,subject,from,toRecipients,ccRecipients,receivedDateTime,sentDateTime,"
    "hasAttachments,body"
)
PAGE = 50
MAX_PER_RUN = 200
MAX_BODY = 100_000
SEARCH_CONFIG = "outil_fr"


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _address(data: Any) -> tuple[str, str]:
    email = (data or {}).get("emailAddress") or {}
    return str(email.get("address", ""))[:254].lower(), str(email.get("name", ""))[:200]


def update_search(message: MailMessage) -> None:
    MailMessage.objects.filter(pk=message.pk).update(
        search=SearchVector(Value(message.subject), weight="A", config=SEARCH_CONFIG)
        + SearchVector(Value(f"{message.from_name} {message.from_address}"), weight="A",
                       config=SEARCH_CONFIG)
        + SearchVector(Value(message.attachment_names), weight="B", config=SEARCH_CONFIG)
        + SearchVector(Value(message.body[:MAX_BODY]), weight="C", config=SEARCH_CONFIG)
    )  # fmt: skip


def _attachments(session: graph.Session, message: MailMessage, clients: Any) -> None:
    data = session.get(f"/me/messages/{message.graph_id}/attachments")
    names = []
    for item in data.get("value", [])[:20]:
        if item.get("@odata.type") != "#microsoft.graph.fileAttachment" or item.get("isInline"):
            continue
        name = str(item.get("name") or "piece-jointe")[:255]
        try:
            content = base64.b64decode(str(item.get("contentBytes", "")), validate=True)
        except (binascii.Error, ValueError):
            continue
        if not content or len(content) > settings.DOCUMENT_MAX_BYTES:
            continue
        try:
            content_type = detect_type(SimpleUploadedFile(name, content)).content_type
        except ValidationError:
            content_type = "application/octet-stream"
        kind, label = recognize.recognize(name, content, content_type, clients)
        attachment = MailAttachment(
            message=message, name=name, content_type=content_type, size=len(content),
            sha256=hashlib.sha256(content).hexdigest(), kind=kind, label=label,
        )  # fmt: skip
        attachment.file.save("piece", ContentFile(content), save=False)
        attachment.save()
        names.append(name)
    if names:
        message.attachment_names = " ".join(names)[:5000]
        message.save(update_fields=["attachment_names"])


def _store(session: graph.Session, item: dict[str, Any], folder: str, date_field: str) -> bool:
    link = session.link
    owner = link.user
    graph_id = str(item.get("id", ""))[:255]
    if not graph_id or MailExclusion.objects.filter(owner=owner, graph_id=graph_id).exists():
        return False
    if MailMessage.objects.filter(owner=owner, graph_id=graph_id).exists():
        return False
    when = parse_datetime(str(item.get(date_field) or "")) or timezone.now()
    from_address, from_name = _address(item.get("from"))
    recipients = [_address(r)[0] for r in (item.get("toRecipients") or [])]
    recipients += [_address(r)[0] for r in (item.get("ccRecipients") or [])]
    recipients = [r for r in recipients if r][:50]
    body = str(((item.get("body") or {}).get("content")) or "")[:MAX_BODY]
    subject = str(item.get("subject") or "")[:300]
    sent = folder == MailMessage.Folder.SENT
    suggestion = classify.suggest(
        addresses=recipients if sent else [from_address], subject=subject, body=body, user=owner
    )
    with transaction.atomic():
        message = MailMessage.objects.create(
            owner=owner, graph_id=graph_id, folder=folder,
            conversation_id=str(item.get("conversationId") or "")[:255],
            from_address=from_address, from_name=from_name, to_addresses=recipients,
            subject=subject, body=body, received_at=when,
            read_at=when if sent else None,
            suggested_client=suggestion.client, suggested_person=suggestion.person,
            choice_needed=suggestion.choice_needed, reason=suggestion.reason[:120],
            # Un e-mail envoyé est rangé tout de suite (pas d'adresse privée à trancher).
            client=suggestion.client if sent and not suggestion.choice_needed else None,
            classed_at=when if sent and suggestion.client and not suggestion.choice_needed
            else None,
        )  # fmt: skip
    if item.get("hasAttachments"):
        _attachments(session, message, Client.objects.visible_to(owner))
    update_search(message)
    if not sent:
        _close_awaiting(message)
    return True


def _close_awaiting(message: MailMessage) -> None:
    """Une réponse est arrivée : les attentes de cette adresse ou conversation se ferment."""
    match = Q(address__iexact=message.from_address)
    if message.conversation_id:
        match |= Q(conversation_id=message.conversation_id)
    Awaiting.objects.filter(
        owner=message.owner, done_at__isnull=True, since__lt=message.received_at
    ).filter(match).update(done_at=timezone.now(), answer=message)


def sync_link(link: MailboxLink, http: Any = None) -> int:
    """Relève une boîte ; renvoie le nombre de nouveaux e-mails copiés."""
    if not link.read_enabled or link.broken_at is not None or link.read_since is None:
        return 0
    try:
        session = graph.Session(link, http)
        count = 0
        for path, folder, date_field, cursor_field in FOLDERS:
            since = getattr(link, cursor_field) or link.read_since
            url = f"/me/mailFolders/{path}/messages"
            params: dict[str, str] | None = {
                "$filter": f"{date_field} ge {_iso(since)}", "$orderby": f"{date_field} asc",
                "$top": str(PAGE), "$select": SELECT,
            }  # fmt: skip
            newest = since
            seen = 0
            while url and seen < MAX_PER_RUN:
                data = session.get(url, params, text_body=True)
                for item in data.get("value", []):
                    seen += 1
                    count += _store(session, item, folder, date_field)
                    when = parse_datetime(str(item.get(date_field) or ""))
                    if when and when > newest:
                        newest = when
                url, params = str(data.get("@odata.nextLink") or ""), None
            setattr(link, cursor_field, newest)
        link.last_sync_at = timezone.now()
        link.sync_error = ""
        link.save(update_fields=["inbox_cursor", "sent_cursor", "last_sync_at", "sync_error"])
        return count
    except graph.MailboxError as error:
        link.sync_error = str(error)[:200]
        link.save(update_fields=["sync_error"])
        logger.warning("Relève de boîte interrompue (employé %s)", link.user_id)
        return 0


def sync_all() -> int:
    if not graph.configured():
        return 0
    links = MailboxLink.objects.filter(read_enabled=True, broken_at__isnull=True)
    return sum(sync_link(link) for link in links.select_related("user"))


def purge(now: datetime | None = None) -> int:
    """Conservation : non classé, 1 an ; classé, 10 ans après la fin de la relation."""
    now = now or timezone.now()
    old = now - timedelta(days=settings.MAIL_UNCLASSED_DAYS)
    gone = MailMessage.objects.filter(classed_at__isnull=True, received_at__lt=old)
    ended = now.date() - timedelta(days=round(365.25 * settings.MAIL_KEEP_YEARS_AFTER_CLIENT))
    gone_client = MailMessage.objects.filter(
        classed_at__isnull=False, client__client_until__lt=ended
    )
    count = 0
    for message in [*gone, *gone_client]:
        delete(message)
        count += 1
    return count


def delete(message: MailMessage) -> None:
    for attachment in message.attachments.all():
        attachment.file.delete(save=False)
    message.delete()
