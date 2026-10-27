"""Documents des clients et demandes « À recevoir » (D-033, D-034).

Un document est soit « en cours » (rangé dans une case de l'onglet Documents), soit archivé
(dans un dossier des Archives). Le fichier est stocké dans un espace privé (`documents`) : il
n'a jamais d'adresse publique et ne se lit que par une vue qui vérifie les droits et
journalise. Son nom de stockage est aléatoire (aucun nom de client dans les chemins).
"""

from __future__ import annotations

import secrets
import uuid
from typing import ClassVar

from django.core.files.storage import Storage, storages
from django.db import models
from django.utils import timezone

from apps.clients.models import Client
from apps.core.models import User


def documents_storage() -> Storage:
    return storages["documents"]


def new_reference() -> str:
    return secrets.token_hex(5).upper()


def _storage_name(instance: Document, filename: str) -> str:
    return f"{timezone.now():%Y/%m}/{uuid.uuid4().hex}"


class DocumentRequest(models.Model):
    """Pièce demandée au client, en attente de réception (case « À recevoir »)."""

    class Kind(models.TextChoices):
        IDENTITY_CARD = "identity_card", "Carte d'identité"
        UBO = "ubo", "Confirmation des bénéficiaires effectifs"
        SIGNATURE = "signature", "Document à signer"
        OTHER = "other", "Autre pièce"
        # D-051 : plusieurs pièces demandées en un seul e-mail et un seul lien.
        BUNDLE = "bundle", "Plusieurs documents"

    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        RECEIVED = "received", "Reçue"
        CANCELLED = "cancelled", "Annulée"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="document_requests")
    kind = models.CharField("type", max_length=20, choices=Kind.choices)
    person = models.ForeignKey(
        Client,
        verbose_name="personne concernée",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    title = models.CharField("objet", max_length=200)
    # Type du document attendu (D-037) : décide où il sera rangé à sa réception.
    doc_type = models.CharField("type de document", max_length=40, blank=True)
    recipient = models.EmailField("destinataire", blank=True)
    status = models.CharField(
        "état", max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    # Référence glissée dans l'e-mail : permettra de rattacher la réponse à la demande.
    reference = models.CharField("référence", max_length=20, unique=True, default=new_reference)
    reminders_sent = models.PositiveSmallIntegerField("relances envoyées", default=0)
    next_reminder_on = models.DateField("prochaine relance", null=True, blank=True)
    created_at = models.DateTimeField("demandée le", default=timezone.now)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    closed_at = models.DateTimeField("clôturée le", null=True, blank=True)
    # D-046 : lien sécurisé de dépôt. Seule l'empreinte sert à le retrouver ; le lien lui-même
    # est gardé chiffré pour être remis dans les relances.
    link_hash = models.CharField(max_length=64, unique=True, null=True, blank=True)
    link_token = models.TextField(blank=True)
    link_expires_at = models.DateTimeField("lien valable jusqu'au", null=True, blank=True)
    link_attempts = models.PositiveSmallIntegerField("essais de dépôt", default=0)
    bundle = models.ForeignKey(
        "self",
        verbose_name="demande groupée",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="items",
    )

    class Meta:
        verbose_name = "demande de document"
        verbose_name_plural = "demandes de documents"
        ordering: ClassVar = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class Document(models.Model):
    class Source(models.TextChoices):
        UPLOAD = "upload", "Déposé à la main"
        REQUEST = "request", "Reçu en réponse à une demande"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="documents")
    title = models.CharField("titre", max_length=200)
    # Où il se trouve : une case de l'onglet Documents (en cours) ou un dossier d'archives.
    case = models.CharField("case", max_length=40, blank=True, db_index=True)
    folder = models.CharField("dossier d'archives", max_length=40, blank=True, db_index=True)
    person = models.ForeignKey(
        Client,
        verbose_name="personne concernée",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    request = models.ForeignKey(
        DocumentRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.UPLOAD)
    auto_filed = models.BooleanField("classé automatiquement", default=False)
    file = models.FileField(storage=documents_storage, upload_to=_storage_name, max_length=200)
    original_name = models.CharField("nom du fichier", max_length=255)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField("taille")
    # Empreinte des données du dossier utilisées par un document produit par l'outil (D-050).
    data_fingerprint = models.JSONField("empreinte des données", default=dict, blank=True)
    # Questions posées au client quand il signe en ligne (D-071, déclaration UBO) :
    # [{"person": id, "name": "…"}] — une ligne par bénéficiaire effectif.
    questions = models.JSONField("questions au signataire", default=list, blank=True)
    sha256 = models.CharField(max_length=64)
    uploaded_at = models.DateTimeField("ajouté le", default=timezone.now)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    archived_at = models.DateTimeField("archivé le", null=True, blank=True)

    # D-039 : un document généré par l'outil est d'abord un brouillon, puis éventuellement
    # envoyé au client pour signature ; il ne compte qu'une fois définitif.
    class State(models.TextChoices):
        FINAL = "final", "Définitif"
        DRAFT = "draft", "Brouillon"
        AWAITING_SIGNATURE = "awaiting_signature", "Envoyé pour signature"

    state = models.CharField(
        "état", max_length=20, choices=State.choices, default=State.FINAL, db_index=True
    )
    generated = models.BooleanField("généré par l'outil", default=False)
    # Type de document (D-037, voir types.py) et date d'expiration éventuelle.
    doc_type = models.CharField("type", max_length=40, blank=True, db_index=True)
    expires_on = models.DateField("expire le", null=True, blank=True)
    # Lecture automatique (D-035) : si un contrôle coince, le document est « à confirmer ».
    review_needed = models.BooleanField("à confirmer", default=False)
    review_reason = models.CharField("raison", max_length=200, blank=True)

    class Meta:
        verbose_name = "document"
        verbose_name_plural = "documents"
        ordering: ClassVar = ["-uploaded_at"]
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=~models.Q(case="", folder=""), name="document_has_place"
            )
        ]

    def __str__(self) -> str:
        return self.title


class OutgoingEmail(models.Model):
    """E-mail au client pour une demande. Il part de la boîte Outlook reliée de l'équipe du
    dossier (D-045) ; sans boîte reliée, il est seulement préparé (`delivered` = faux)."""

    class Kind(models.TextChoices):
        REQUEST = "request", "Demande"
        REMINDER = "reminder", "Relance"

    request = models.ForeignKey(DocumentRequest, on_delete=models.CASCADE, related_name="emails")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    to = models.EmailField("à", blank=True)
    subject = models.CharField("objet", max_length=255)
    body = models.TextField("message")
    created_at = models.DateTimeField(default=timezone.now)
    delivered = models.BooleanField("envoyé", default=False)
    sent_from = models.EmailField("envoyé depuis", blank=True)  # boîte Outlook (D-045)

    class Meta:
        verbose_name = "e-mail sortant"
        verbose_name_plural = "e-mails sortants"
        ordering: ClassVar = ["created_at"]

    def __str__(self) -> str:
        return self.subject


class IdentityCard(models.Model):
    """Carte d'identité d'une personne (mandataire, actionnaire, client IPP) — D-035.

    Le numéro national lu sur la carte n'est jamais conservé ici : il sert seulement à vérifier
    que la carte correspond à la fiche.
    """

    class Source(models.TextChoices):
        READ = "read", "Lue automatiquement"
        MANUAL = "manual", "Encodée à la main"

    person = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="identity_cards")
    document = models.ForeignKey(
        Document, on_delete=models.SET_NULL, null=True, blank=True, related_name="identity_cards"
    )
    card_number = models.CharField("numéro de carte", max_length=20, blank=True)
    valid_until = models.DateField("valable jusqu'au")
    source = models.CharField(max_length=20, choices=Source.choices)
    auto_applied = models.BooleanField("appliqué automatiquement", default=False)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "carte d'identité"
        verbose_name_plural = "cartes d'identité"
        ordering: ClassVar = ["-valid_until", "-created_at"]

    def __str__(self) -> str:
        return f"Carte de {self.person} (jusqu'au {self.valid_until:%d/%m/%Y})"

    @property
    def masked_number(self) -> str:
        digits = self.card_number
        return f"•••• {digits[-4:]}" if len(digits) > 4 else digits


def _inbox_name(instance: InboxItem, filename: str) -> str:
    return f"depot/{timezone.now():%Y/%m}/{uuid.uuid4().hex}"


class InboxItem(models.Model):
    """Fichier déposé dans le dépôt unique que l'outil n'a pas su classer seul (D-041).

    Il n'appartient encore à aucun dossier : seule la personne qui l'a déposé le voit, et il
    est effacé s'il n'est pas classé dans les `INBOX_RETENTION_DAYS` jours.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(storage=documents_storage, upload_to=_inbox_name, max_length=200)
    original_name = models.CharField("nom du fichier", max_length=255)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField("taille")
    sha256 = models.CharField(max_length=64)
    reason = models.CharField("pourquoi il n'a pas été classé", max_length=200, blank=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField("déposé le", default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "document à classer"
        verbose_name_plural = "documents à classer"
        ordering: ClassVar = ["-uploaded_at"]

    def __str__(self) -> str:
        return self.original_name


class Signature(models.Model):
    """Preuve d'une signature en ligne par le client (D-048).

    Signature électronique « simple » (dessinée), avec piste d'audit : qui, quand, d'où, et
    l'empreinte du document lu puis du document signé (toute modification se verrait).
    """

    request = models.ForeignKey(
        DocumentRequest, on_delete=models.PROTECT, related_name="signatures"
    )
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name="signatures")
    signer_name = models.CharField("signataire", max_length=150)
    signer_role = models.CharField("qualité", max_length=100, blank=True)
    signed_at = models.DateTimeField("signé le", default=timezone.now)
    ip_address = models.GenericIPAddressField("adresse IP", null=True, blank=True)
    user_agent = models.CharField("navigateur", max_length=255, blank=True)
    original_sha256 = models.CharField("empreinte du document lu", max_length=64)
    signed_sha256 = models.CharField("empreinte du document signé", max_length=64)
    # Réponses du client aux questions du document (D-071) : {"<id>": {"pep": bool, "lieu": "…"}}
    answers = models.JSONField("réponses du signataire", default=dict, blank=True)

    class Meta:
        verbose_name = "signature en ligne"
        verbose_name_plural = "signatures en ligne"
        ordering: ClassVar = ["-signed_at"]

    def __str__(self) -> str:
        return f"{self.signer_name} — {self.signed_at:%d/%m/%Y}"


class RiskAssessment(models.Model):
    """Fiche de détermination du niveau de risque, remplie avec l'outil (D-049)."""

    class Level(models.TextChoices):
        LOW = "low", "Faible"
        MEDIUM = "medium", "Standard"  # terme du modèle ITAA (D-076)
        HIGH = "high", "Élevé"

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="risk_assessments")
    answers = models.JSONField("réponses", default=dict)
    score = models.PositiveSmallIntegerField("points")
    level = models.CharField("niveau", max_length=10, choices=Level.choices)
    next_review = models.DateField("prochaine révision")
    comment = models.TextField("commentaire", blank=True)
    document = models.ForeignKey(
        Document, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField("établie le", default=timezone.now)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Risque élevé : acceptation au niveau hiérarchique adéquat (norme ITAA, point 4.2).
    approved_at = models.DateTimeField("validée par l'AMLCO le", null=True, blank=True)
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "évaluation du risque"
        verbose_name_plural = "évaluations du risque"
        ordering: ClassVar = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.client} — {self.get_level_display()} ({self.created_at:%d/%m/%Y})"

    @property
    def awaiting_approval(self) -> bool:
        return self.level == self.Level.HIGH and self.approved_at is None


class LetterTemplate(models.Model):
    """Modèle Word de lettre de mission propre au cabinet (D-069).

    Déposé tel quel par un administrateur. L'outil y repère les trous (XXX, ……, [à compléter],
    texte surligné) ; `holes` dit ce que chacun contient, `options` quels paragraphes ne sont
    gardés que sous condition, `checks` quels éléments obligatoires de l'ITAA ont été confirmés.
    Un seul modèle actif à la fois ; les anciennes versions restent pour l'historique."""

    name = models.CharField("nom du fichier", max_length=200)
    content = models.BinaryField("fichier Word")
    holes = models.JSONField("trous et leur contenu", default=dict, blank=True)
    options = models.JSONField("paragraphes à options", default=dict, blank=True)
    checks = models.JSONField("éléments obligatoires confirmés", default=list, blank=True)
    active = models.BooleanField("utilisé pour les nouvelles lettres", default=False)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering: ClassVar = ["-uploaded_at"]
        verbose_name = "modèle de lettre de mission"

    def __str__(self) -> str:
        return self.name
