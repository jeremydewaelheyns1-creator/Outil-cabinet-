"""Actions de « Ma boîte mail » (D-060). Chaque action vérifie que l'e-mail appartient à
l'employé et que le dossier choisi lui est visible ; les actions sont journalisées par les
vues (sans le contenu des e-mails)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.clients.models import Client
from apps.core.models import User
from apps.outlook import graph

from . import classify, richtext
from .models import Awaiting, MailAttachment, MailExclusion, MailMessage, ScheduledMail
from .sync import delete


def mark_read(message: MailMessage) -> None:
    if message.read_at is None:
        message.read_at = timezone.now()
        message.save(update_fields=["read_at"])


def target_for(message: MailMessage, choice: str, user: User) -> tuple[Client, Client | None]:
    """Où classer : le choix fait (adresse privée) ou la suggestion de l'outil."""
    if choice:
        return classify.resolve(choice, user)
    if message.suggested_client is None:
        raise ValueError("Choisissez d'abord un dossier (clic droit › Reclasser dans…).")
    if message.choice_needed:
        raise ValueError("Adresse privée : choisissez société ou personne physique.")
    visible = Client.objects.visible_to(user)
    return visible.get(pk=message.suggested_client.pk), None


def file_message(message: MailMessage, client: Client, person: Client | None) -> None:
    """« Traité : classer » ou « Reclasser » : l'e-mail quitte la boîte de réception."""
    message.client, message.person = client, person
    message.classed_at = timezone.now()
    message.choice_needed = False
    message.save(update_fields=["client", "person", "classed_at", "choice_needed"])


def unclass(message: MailMessage) -> None:
    message.classed_at = None
    message.save(update_fields=["classed_at"])


def remove_private(message: MailMessage) -> None:
    """« Privé : retirer » : la copie est effacée et ne reviendra plus."""
    MailExclusion.objects.get_or_create(owner=message.owner, graph_id=message.graph_id)
    delete(message)


def wait_for(owner: User, *, address: str, subject: str, client: Client | None,
             conversation_id: str = "") -> Awaiting:  # fmt: skip
    return Awaiting.objects.create(
        owner=owner, address=address[:254], subject=subject[:300], client=client,
        conversation_id=conversation_id[:255],
    )  # fmt: skip


def _inline(html: str) -> tuple[str, list[graph.Attachment]]:
    """Le logo du cabinet joint au message s'il est dans la signature (retiré entre-temps :
    la balise est enlevée pour ne pas montrer d'image cassée)."""
    from apps.core import logo
    from apps.core.models import CabinetSettings

    marker = f'src="cid:{logo.CONTENT_ID}"'
    if marker not in html:
        return html, []
    data = bytes(CabinetSettings.current().signature_logo or b"")
    if not data:
        return re.sub(r'<img src="cid:[^"]*"[^>]*>', "", html), []
    return html, [graph.Attachment("logo.png", data, "image/png", content_id=logo.CONTENT_ID)]


def reply(message: MailMessage, html: str, *, wait: bool) -> None:
    """Réponse écrite par l'employé, envoyée depuis sa boîte Outlook (fil de discussion
    gardé). L'e-mail reste dans la boîte de réception jusqu'à « Traité : classer ».
    `html` : message déjà nettoyé (`richtext.body`)."""
    if not richtext.to_text(html):
        raise ValidationError("Écrivez votre réponse.")
    link = graph.mailbox_for(message.owner)
    if link is None:
        raise ValidationError("Votre boîte Outlook n'est pas reliée.")
    html, inline = _inline(html)
    graph.Session(link).reply(message.graph_id, html, inline)
    message.replied_at = timezone.now()
    message.save(update_fields=["replied_at"])
    if wait and message.from_address:
        wait_for(message.owner, address=message.from_address, subject=message.subject,
                 client=message.client or message.suggested_client,
                 conversation_id=message.conversation_id)  # fmt: skip


def _check_new(owner: User, to: str, html: str) -> None:
    if graph.mailbox_for(owner) is None:
        raise ValidationError("Votre boîte Outlook n'est pas reliée.")
    if not to or "@" not in to or not richtext.to_text(html):
        raise ValidationError("Indiquez le destinataire et le message.")


def send_new(owner: User, *, to: str, subject: str, html: str, client: Client | None,
             wait: bool) -> None:  # fmt: skip
    _check_new(owner, to.strip(), html)
    link = graph.mailbox_for(owner)
    if link is None:  # déjà vérifié : boîte déliée entre-temps
        raise ValidationError("Votre boîte Outlook n'est pas reliée.")
    html, inline = _inline(html)
    graph.send(link, to=to.strip(), subject=subject.strip()[:300], body=html, html=True,
               attachments=inline)  # fmt: skip
    if wait:
        wait_for(owner, address=to.strip(), subject=subject, client=client)


# --- Envoi programmé ------------------------------------------------------------------------

LATEST = timedelta(days=366)


def parse_send_at(value: str) -> datetime | None:
    """« 2026-10-27T08:30 » (champ date et heure du navigateur), heure belge. Vide : None."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        naive = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError("Date et heure d'envoi non reconnues.") from exc
    if timezone.is_aware(naive):
        return naive
    return timezone.make_aware(naive, timezone.get_current_timezone())


def schedule(owner: User, *, send_at: datetime, html: str, to: str = "", subject: str = "",
             reply_to: MailMessage | None = None, client: Client | None = None,
             wait: bool = False) -> ScheduledMail:  # fmt: skip
    """Programme un nouveau message (ou une réponse) : envoyé à l'heure choisie."""
    now = timezone.now()
    if send_at <= now + timedelta(minutes=1):
        raise ValidationError("Choisissez une heure d'envoi dans le futur.")
    if send_at > now + LATEST:
        raise ValidationError("Un envoi se programme au plus un an à l'avance.")
    if reply_to is not None:
        if reply_to.owner_id != owner.pk:
            raise ValidationError("E-mail introuvable.")
        if not richtext.to_text(html):
            raise ValidationError("Écrivez votre réponse.")
        if graph.mailbox_for(owner) is None:
            raise ValidationError("Votre boîte Outlook n'est pas reliée.")
        to = reply_to.from_address
        subject = (
            reply_to.subject
            if reply_to.subject.lower().startswith(("re:", "re :"))
            else (f"RE: {reply_to.subject}" if reply_to.subject else "")
        )
        client = client or reply_to.client or reply_to.suggested_client
    else:
        _check_new(owner, to.strip(), html)
    return ScheduledMail.objects.create(
        owner=owner, reply_to=reply_to, to=to.strip()[:254], subject=subject.strip()[:300],
        html=html, client=client, wait=wait, send_at=send_at,
    )  # fmt: skip


def _forget(item: ScheduledMail, **fields: Any) -> None:
    """Parti, annulé ou abandonné : le contenu quitte l'outil (Outlook garde l'original)."""
    for name, value in fields.items():
        setattr(item, name, value)
    item.html = ""
    item.save()


def deliver(item: ScheduledMail) -> None:
    """Envoie maintenant un message programmé (lève MailboxError / ValidationError)."""
    if not item.pending:
        return
    if item.reply_to_id is not None and item.reply_to is not None:
        reply(item.reply_to, item.html, wait=item.wait)
    else:
        send_new(item.owner, to=item.to, subject=item.subject, html=item.html,
                 client=item.client, wait=item.wait)  # fmt: skip
    _forget(item, sent_at=timezone.now(), error="")


def cancel(item: ScheduledMail) -> None:
    if item.pending:
        _forget(item, cancelled_at=timezone.now())


def send_due(now: datetime | None = None) -> int:
    """Passage périodique (`run_jobs`) : envoie les messages dont l'heure est venue. Après
    trois échecs, le message est abandonné et son auteur prévenu dans la cloche."""
    from apps.core.models import Notification

    now = now or timezone.now()
    sent = 0
    due = ScheduledMail.objects.filter(
        send_at__lte=now, sent_at__isnull=True, cancelled_at__isnull=True, failed_at__isnull=True
    ).select_related("owner", "reply_to", "client")
    for item in due:
        try:
            deliver(item)
            sent += 1
        except (ValidationError, graph.MailboxError) as error:
            item.attempts += 1
            item.error = (" ".join(error.messages) if isinstance(error, ValidationError)
                          else str(error))[:200]  # fmt: skip
            if item.attempts < ScheduledMail.MAX_ATTEMPTS:
                item.save(update_fields=["attempts", "error"])
                continue
            _forget(item, failed_at=now)
            Notification.objects.get_or_create(
                user=item.owner, key=f"programme:{item.pk}",
                defaults={"title": f"Message programmé non envoyé : {item}"[:200],
                          "lines": [item.error, "Il n'est pas parti : réécrivez-le si besoin."],
                          "link": "/boite-mail/?vue=programmes"},
            )  # fmt: skip
    return sent


def file_attachment(attachment: MailAttachment, user: User, place: str = "") -> str:
    """« Ranger dans le dossier » : la pièce rejoint le vrai dossier (Documents, TVA…).
    Déclarations TVA et cartes d'identité passent par le dépôt unique (D-041), qui les lit et
    les range ; pour le reste, l'employé choisit l'endroit. Renvoie un message lisible."""
    from apps.documents import inbox
    from apps.documents import services as documents

    message = attachment.message
    client = message.client or message.suggested_client
    with attachment.file.open("rb") as handle:
        upload = SimpleUploadedFile(attachment.name, handle.read(), attachment.content_type)
    visible = Client.objects.visible_to(user)
    if attachment.kind in (MailAttachment.Kind.VAT, MailAttachment.Kind.CARD) and not place:
        result = inbox.receive([upload], clients=visible, user=user)[0]
        if result.level in (inbox.OK, inbox.DOUBT):
            attachment.filed_at = timezone.now()
            attachment.save(update_fields=["filed_at"])
        return result.message
    if client is None or not visible.filter(pk=client.pk).exists():
        raise ValidationError("Classez d'abord l'e-mail dans un dossier.")
    if place not in {value for value, _ in inbox.places(client)}:
        raise ValidationError("Choisissez où ranger la pièce.")
    kind, _, slug = place.partition(":")
    document = documents.store(
        client, upload, title=attachment.label or attachment.name,
        case=slug if kind == "case" else "", folder=slug if kind == "folder" else "",
        person=message.person, user=user,
    )  # fmt: skip
    attachment.filed_document = document
    attachment.filed_at = timezone.now()
    attachment.save(update_fields=["filed_document", "filed_at"])
    return f"« {attachment.name} » rangé dans le dossier {client.display_name}."
