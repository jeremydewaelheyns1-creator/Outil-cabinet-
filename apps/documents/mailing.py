"""Envoi réel des e-mails de l'outil et copie dans « Archives › Courriels » (D-045).

- Un e-mail part de la boîte Outlook reliée de l'employé (D-044) : celui qui a fait la
  demande, sinon le responsable du dossier, sinon son assistant. Sans boîte reliée, il reste
  « préparé » et l'outil le dit.
- Chaque e-mail réellement parti est gardé en PDF dans les archives « Courriels » du dossier
  (de, à, date, objet, texte, noms des pièces jointes).
- Si Microsoft refuse, rien n'est marqué comme envoyé ; le journal ne garde que la référence.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.utils import timezone

from apps.clients.models import Assignment, Client
from apps.core.models import User
from apps.outlook import graph

from .models import Document, OutgoingEmail

logger = logging.getLogger(__name__)


def sender_for(client: Client, user: User | None) -> User | None:
    """Qui envoie : l'employé qui agit (s'il a relié sa boîte), sinon l'équipe du dossier."""
    if graph.mailbox_for(user) is not None:
        return user
    team = {a.role: a.user for a in client.assignments.select_related("user")}
    for role in (Assignment.Role.MANAGER, Assignment.Role.ASSISTANT):
        candidate = team.get(role)
        if graph.mailbox_for(candidate) is not None:
            return candidate
    return user


def archive_copy(
    client: Client,
    *,
    sender: str,
    to: str,
    subject: str,
    body: str,
    sent_at: datetime,
    attachments: Sequence[str] = (),
    user: User | None = None,
) -> Document:
    """Copie PDF de l'e-mail envoyé, rangée dans les archives « Courriels » du dossier."""
    from weasyprint import HTML

    from . import services

    html = render_to_string(
        "documents/courriel.html",
        {
            "cabinet": settings.CABINET_NAME,
            "sender": sender,
            "to": to,
            "subject": subject,
            "body": body,
            "sent_at": timezone.localtime(sent_at),
            "attachments": list(attachments),
        },
    )
    content = bytes(HTML(string=html).write_pdf())
    upload = SimpleUploadedFile("courriel.pdf", content, content_type="application/pdf")
    title = f"Courriel du {timezone.localtime(sent_at):%d/%m/%Y} — {subject}"[:200]
    return services.store(client, upload, title=title, folder="courriels", user=user)


def deliver(email: OutgoingEmail, user: User | None = None) -> bool:
    """Envoie une demande (ou une relance) depuis la boîte Outlook de l'équipe du dossier."""
    request = email.request
    if not email.to or email.delivered:
        return email.delivered
    sender = sender_for(request.client, user or request.created_by)
    link = graph.mailbox_for(sender)
    if link is None:
        return False
    try:
        graph.send(link, to=email.to, subject=email.subject, body=email.body)
    except graph.MailboxError:
        logger.warning("Demande %s : e-mail non parti (Microsoft a refusé)", request.reference)
        return False
    email.delivered = True
    email.sent_from = link.address
    email.save(update_fields=["delivered", "sent_from"])
    archive_copy(
        request.client, sender=link.address, to=email.to, subject=email.subject,
        body=email.body, sent_at=timezone.now(), user=sender,
    )  # fmt: skip
    return True
