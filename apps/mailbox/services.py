"""Actions de « Ma boîte mail » (D-060). Chaque action vérifie que l'e-mail appartient à
l'employé et que le dossier choisi lui est visible ; les actions sont journalisées par les
vues (sans le contenu des e-mails)."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django.utils.html import escape, linebreaks

from apps.clients.models import Client
from apps.core.models import User
from apps.outlook import graph

from . import classify
from .models import Awaiting, MailAttachment, MailExclusion, MailMessage
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


def reply(message: MailMessage, text: str, *, wait: bool) -> None:
    """Réponse écrite par l'employé, envoyée depuis sa boîte Outlook (fil de discussion
    gardé). L'e-mail reste dans la boîte de réception jusqu'à « Traité : classer »."""
    text = text.strip()
    if not text:
        raise ValidationError("Écrivez votre réponse.")
    link = graph.mailbox_for(message.owner)
    if link is None:
        raise ValidationError("Votre boîte Outlook n'est pas reliée.")
    graph.Session(link).reply(message.graph_id, linebreaks(escape(text)))
    message.replied_at = timezone.now()
    message.save(update_fields=["replied_at"])
    if wait and message.from_address:
        wait_for(message.owner, address=message.from_address, subject=message.subject,
                 client=message.client or message.suggested_client,
                 conversation_id=message.conversation_id)  # fmt: skip


def send_new(owner: User, *, to: str, subject: str, body: str, client: Client | None,
             wait: bool) -> None:  # fmt: skip
    link = graph.mailbox_for(owner)
    if link is None:
        raise ValidationError("Votre boîte Outlook n'est pas reliée.")
    if not to or "@" not in to or not body.strip():
        raise ValidationError("Indiquez le destinataire et le message.")
    graph.send(link, to=to.strip(), subject=subject.strip()[:300], body=body)
    if wait:
        wait_for(owner, address=to.strip(), subject=subject, client=client)


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
