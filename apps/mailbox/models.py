"""« Ma boîte mail » (D-060) : copie des e-mails de l'employé, rangés par dossier.

- Chaque employé active lui-même la lecture de sa boîte Outlook ; seul lui voit ses e-mails
  dans l'outil (pas de partage entre collègues). Outlook reste la boîte d'origine.
- Le corps est gardé **en texte simple** (jamais de HTML : rien d'actif ne s'affiche).
- Un e-mail arrive dans la boîte de réception avec une **suggestion** de dossier ; il n'est
  rangé (`client`, éventuellement `person` = sous-dossier « personne physique ») que quand
  l'employé clique « Traité : classer » ou le reclasse lui-même.
- « Privé : retirer » efface la copie et l'empêche de revenir (`MailExclusion`).
- Conservation : non rangé, 1 an ; rangé, jusqu'à 10 ans après la fin de la relation.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.utils import timezone

from apps.clients.models import Client
from apps.core.models import User
from apps.documents.models import Document, documents_storage


class MailMessage(models.Model):
    class Folder(models.TextChoices):
        INBOX = "inbox", "Réception"
        SENT = "sent", "Envoyés"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mails")
    graph_id = models.CharField(max_length=255)
    conversation_id = models.CharField(max_length=255, blank=True)
    folder = models.CharField(max_length=10, choices=Folder.choices, default=Folder.INBOX)
    from_address = models.EmailField("de (adresse)", blank=True)
    from_name = models.CharField("de", max_length=200, blank=True)
    to_addresses = models.JSONField("à", default=list, blank=True)
    subject = models.CharField("objet", max_length=300, blank=True)
    body = models.TextField("texte", blank=True)
    attachment_names = models.TextField(blank=True)  # pour la recherche
    received_at = models.DateTimeField("reçu le", db_index=True)
    read_at = models.DateTimeField("lu le", null=True, blank=True)
    replied_at = models.DateTimeField("répondu le", null=True, blank=True)
    # Suggestion de l'outil (avant « Traité : classer »)
    suggested_client = models.ForeignKey(
        Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    suggested_person = models.ForeignKey(
        Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    choice_needed = models.BooleanField("adresse privée : société ou personne ?", default=False)
    reason = models.CharField("pourquoi ce dossier", max_length=120, blank=True)
    # Rangement décidé par l'employé
    client = models.ForeignKey(
        Client, verbose_name="dossier", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="mails",
    )  # fmt: skip
    person = models.ForeignKey(
        Client, verbose_name="personne physique", on_delete=models.SET_NULL, null=True,
        blank=True, related_name="+",
    )  # fmt: skip
    classed_at = models.DateTimeField("classé le", null=True, blank=True)
    search = SearchVectorField(null=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = "e-mail"
        verbose_name_plural = "e-mails"
        ordering: ClassVar = ["-received_at"]
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["owner", "graph_id"], name="one_copy_per_mail")
        ]
        indexes: ClassVar = [
            GinIndex(fields=["search"], name="mail_search"),
            models.Index(fields=["owner", "folder", "classed_at"]),
            models.Index(fields=["owner", "client"]),
        ]

    def __str__(self) -> str:
        return f"E-mail du {self.received_at:%d/%m/%Y}"

    @property
    def is_unread(self) -> bool:
        return self.read_at is None

    @property
    def sender(self) -> str:
        return self.from_name or self.from_address or "—"


def _attachment_name(instance: MailAttachment, filename: str) -> str:
    return f"boite/{timezone.now():%Y/%m}/{uuid.uuid4().hex}"


class MailAttachment(models.Model):
    class Kind(models.TextChoices):
        VAT = "tva", "Déclaration TVA"
        CARD = "carte", "Carte d'identité"
        UBO = "ubo", "Extrait du registre UBO"
        TAX = "impot", "Courrier des impôts"
        INVOICE = "facture", "Facture"
        OTHER = "autre", "Document"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(MailMessage, on_delete=models.CASCADE, related_name="attachments")
    name = models.CharField("nom", max_length=255)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField("taille")
    file = models.FileField(storage=documents_storage, upload_to=_attachment_name, max_length=200)
    sha256 = models.CharField(max_length=64)
    kind = models.CharField(
        "reconnu comme", max_length=10, choices=Kind.choices, default=Kind.OTHER
    )
    label = models.CharField("description", max_length=200, blank=True)
    filed_document = models.ForeignKey(
        Document, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    filed_at = models.DateTimeField("rangé dans le dossier le", null=True, blank=True)

    class Meta:
        verbose_name = "pièce jointe"
        verbose_name_plural = "pièces jointes"
        ordering: ClassVar = ["name"]

    def __str__(self) -> str:
        return self.name


class MailExclusion(models.Model):
    """E-mail retiré comme privé : il ne sera plus jamais copié dans l'outil."""

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    graph_id = models.CharField(max_length=255)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["owner", "graph_id"], name="one_exclusion_per_mail")
        ]

    def __str__(self) -> str:
        return f"E-mail retiré le {self.created_at:%d/%m/%Y}"


class Awaiting(models.Model):
    """« En attente de réponse » : l'employé attend une réponse à un e-mail qu'il a envoyé.
    Se ferme seul quand un e-mail arrive de cette adresse (ou dans la même conversation)."""

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="awaiting")
    address = models.EmailField("adresse attendue")
    subject = models.CharField("objet", max_length=300, blank=True)
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True)
    conversation_id = models.CharField(max_length=255, blank=True)
    since = models.DateTimeField("depuis", default=timezone.now)
    done_at = models.DateTimeField(null=True, blank=True)
    answer = models.ForeignKey(
        MailMessage, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering: ClassVar = ["since"]

    def __str__(self) -> str:
        return self.subject or self.address


class ScheduledMail(models.Model):
    """Message écrit maintenant, envoyé plus tard depuis la boîte Outlook de son auteur.

    - Seul l'auteur le voit, peut l'annuler ou l'envoyer tout de suite.
    - Envoyé par le passage périodique de l'outil (toutes les 5 minutes) : à quelques minutes
      près de l'heure choisie.
    - Une fois parti (ou annulé), son contenu est effacé de l'outil : la copie de référence
      est dans les « Éléments envoyés » d'Outlook. Il n'en reste que l'objet et les dates.
    """

    MAX_ATTEMPTS = 3

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="scheduled_mails")
    reply_to = models.ForeignKey(
        MailMessage, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name="réponse à",
    )  # fmt: skip
    to = models.EmailField("à", blank=True)
    subject = models.CharField("objet", max_length=300, blank=True)
    html = models.TextField("message", blank=True)
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True)
    wait = models.BooleanField("j'attends une réponse", default=False)
    send_at = models.DateTimeField("à envoyer le", db_index=True)
    sent_at = models.DateTimeField("envoyé le", null=True, blank=True)
    cancelled_at = models.DateTimeField("annulé le", null=True, blank=True)
    failed_at = models.DateTimeField("abandonné le", null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering: ClassVar = ["send_at"]
        verbose_name = "envoi programmé"
        verbose_name_plural = "envois programmés"

    def __str__(self) -> str:
        return self.subject or self.to

    @property
    def pending(self) -> bool:
        return self.sent_at is None and self.cancelled_at is None and self.failed_at is None


class Signature(models.Model):
    """Signature personnelle ajoutée aux e-mails écrits dans « Ma boîte mail »."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="mail_signature")
    html = models.TextField("signature", blank=True)  # déjà nettoyée (richtext.clean)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "signature"

    def __str__(self) -> str:
        return f"Signature de {self.user}"
