"""Onglet « Clôture » (D-111) : une ligne par exercice, avec sa checklist comptable et la case
« Clôture comptable ».

- Deux checklists communes (réglages généraux) : dossiers soumis à TVA et non soumis.
  Elles s'appliquent à tous les dossiers.
- Chaque dossier peut personnaliser la sienne (renommer, retirer, ajouter, réordonner) : gardé
  pour toutes les années suivantes, même quand la checklist commune change.
- Chaque exercice garde ses coches, ses commentaires (liés à une ligne : tant qu'un
  commentaire est ouvert, la ligne ne peut pas être verte) et sa remarque générale.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.clients.models import Client
from apps.core.models import User


class Kind(models.TextChoices):
    VAT = "tva", "Dossiers soumis à TVA"
    NO_VAT = "sans_tva", "Dossiers non soumis à TVA"
    MANAGER = "gestionnaire", "Checklist gestionnaire"


class Part(models.TextChoices):
    """Les deux checklists d'un exercice (D-112)."""

    ACCOUNTING = "comptable", "Checklist comptable"
    MANAGER = "gestionnaire", "Checklist gestionnaire"


class CommonItem(models.Model):
    """Un champ d'une checklist commune (réglages généraux)."""

    kind = models.CharField("checklist", max_length=12, choices=Kind.choices)
    label = models.CharField("champ", max_length=80)
    hint = models.CharField("ce qu'il faut vérifier", max_length=200, blank=True)
    position = models.PositiveIntegerField("ordre", default=0)
    active = models.BooleanField("actif", default=True)  # supprimé : gardé pour l'historique
    history = HistoricalRecords()

    class Meta:
        verbose_name = "champ de checklist commune"
        verbose_name_plural = "champs de checklist commune"
        ordering: ClassVar = ["kind", "position", "pk"]

    def __str__(self) -> str:
        return self.label

    @property
    def key(self) -> str:
        return f"c{self.pk}"


class DossierSetup(models.Model):
    """Personnalisation de la checklist d'un dossier : ordre choisi (clés des champs)."""

    client = models.OneToOneField(Client, on_delete=models.CASCADE, related_name="closing_setup")
    order = models.JSONField("ordre des champs", default=list, blank=True)
    # Cases de dépôt retirées pour ce dossier (ex. pas de fiches 281.50), D-113.
    hidden_deposits = models.JSONField("cases de dépôt retirées", default=list, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "checklist personnalisée"
        verbose_name_plural = "checklists personnalisées"

    def __str__(self) -> str:
        return f"Checklist de {self.client}"


class DossierChange(models.Model):
    """Un champ commun retiré ou renommé pour ce dossier seulement."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="closing_changes")
    item = models.ForeignKey(CommonItem, on_delete=models.CASCADE, related_name="changes")
    removed = models.BooleanField("retiré pour ce dossier", default=False)
    label = models.CharField("champ (pour ce dossier)", max_length=80, blank=True)
    hint = models.CharField("aide (pour ce dossier)", max_length=200, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "champ commun adapté au dossier"
        verbose_name_plural = "champs communs adaptés au dossier"
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["client", "item"], name="one_change_per_common_item")
        ]

    def __str__(self) -> str:
        return f"{self.client} : {self.item}"


class DossierItem(models.Model):
    """Un champ ajouté pour ce dossier seulement."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="closing_items")
    part = models.CharField(
        "checklist", max_length=12, choices=Part.choices, default=Part.ACCOUNTING
    )
    label = models.CharField("champ", max_length=80)
    hint = models.CharField("ce qu'il faut vérifier", max_length=200, blank=True)
    active = models.BooleanField("actif", default=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "champ propre au dossier"
        verbose_name_plural = "champs propres au dossier"
        ordering: ClassVar = ["pk"]

    def __str__(self) -> str:
        return self.label

    @property
    def key(self) -> str:
        return f"d{self.pk}"


class ClosingYear(models.Model):
    """Un exercice du dossier (une ligne de l'onglet Clôture)."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="closing_years")
    start = models.DateField("début de l'exercice")
    end = models.DateField("fin de l'exercice")
    manager = models.ForeignKey(
        User, verbose_name="responsable", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )  # fmt: skip
    assistant = models.ForeignKey(
        User, verbose_name="assistant", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )  # fmt: skip
    closed_on = models.DateField("clôture comptable le", null=True, blank=True)
    closed_by = models.ForeignKey(
        User, verbose_name="clôturé par", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )  # fmt: skip
    manager_closed_on = models.DateField("clôture gestionnaire le", null=True, blank=True)
    manager_closed_by = models.ForeignKey(
        User, verbose_name="clôture gestionnaire par", on_delete=models.SET_NULL, null=True,
        blank=True, related_name="+",
    )  # fmt: skip
    remark = models.TextField("remarque (ligne)", blank=True)
    checklist_remark = models.TextField("remarque générale de la checklist", blank=True)
    manager_remark = models.TextField("remarque générale (gestionnaire)", blank=True)
    # Dividende décidé à l'AG (D-115) : « oui » fait apparaître la case Précompte mobilier.
    dividend = models.BooleanField("dividende décidé à l'AG", null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "exercice (clôture)"
        verbose_name_plural = "exercices (clôture)"
        ordering: ClassVar = ["-end"]
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["client", "end"], name="one_closing_per_year")
        ]

    def __str__(self) -> str:
        return f"Clôture {self.end:%Y} — {self.client}"

    @property
    def label(self) -> str:
        """« 2025 », ou « 2025-2026 » pour un exercice à cheval."""
        if self.start.year == self.end.year:
            return str(self.end.year)
        return f"{self.start.year}-{self.end.year}"


class Tick(models.Model):
    """Une ligne cochée de la checklist d'un exercice."""

    class Status(models.TextChoices):
        OK = "ok", "OK"
        NOT_NEEDED = "na", "Pas concerné"

    year = models.ForeignKey(ClosingYear, on_delete=models.CASCADE, related_name="ticks")
    key = models.CharField("champ (clé)", max_length=20)
    label = models.CharField("champ (au moment de la coche)", max_length=80)
    status = models.CharField("état", max_length=4, choices=Status.choices)
    on = models.DateField("le")
    by = models.ForeignKey(
        User, verbose_name="par", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )  # fmt: skip
    history = HistoricalRecords()

    class Meta:
        verbose_name = "ligne cochée"
        verbose_name_plural = "lignes cochées"
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["year", "key"], name="one_tick_per_line")
        ]

    def __str__(self) -> str:
        return f"{self.label} : {self.get_status_display()}"


class Comment(models.Model):
    """Commentaire lié à une ligne : tant qu'il est ouvert, la ligne reste orange."""

    year = models.ForeignKey(ClosingYear, on_delete=models.CASCADE, related_name="comments")
    key = models.CharField("champ (clé)", max_length=20)
    label = models.CharField("champ", max_length=80)
    text = models.TextField("commentaire")
    author = models.ForeignKey(
        User, verbose_name="auteur", on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    resolved_at = models.DateTimeField("réglé le", null=True, blank=True)
    resolved_by = models.ForeignKey(
        User, verbose_name="réglé par", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )  # fmt: skip
    history = HistoricalRecords()

    class Meta:
        verbose_name = "commentaire de checklist"
        verbose_name_plural = "commentaires de checklist"
        ordering: ClassVar = ["created_at"]

    def __str__(self) -> str:
        return f"{self.label} — {self.created_at:%d/%m/%Y}"

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None


class Deposit(models.Model):
    """Une case de dépôt de l'exercice (D-113) : AG, BNB, ISOC, fiches 281.50, annexes 270.
    Cochée à la main, ou toute seule quand le fichier arrive ; reliée à son échéance."""

    class Kind(models.TextChoices):
        AG = "ag", "AG"
        BNB = "bnb", "BNB"
        ISOC = "isoc", "ISOC"
        FICHES_281_50 = "28150", "Fiches 281.50"
        ANNEXES_270 = "270", "Annexes 270"
        # D-115 : cases ajoutées, montrées seulement aux dossiers concernés.
        FICHES_281_20 = "28120", "Fiches 281.20"
        LISTING = "listing", "Listing clients"
        PRECOMPTE = "pm", "Précompte mobilier"

    year = models.ForeignKey(ClosingYear, on_delete=models.CASCADE, related_name="deposits")
    kind = models.CharField("dépôt", max_length=8, choices=Kind.choices)
    done_on = models.DateField("fait le", null=True, blank=True)
    done_by = models.ForeignKey(
        User, verbose_name="par", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )  # fmt: skip
    documents = models.ManyToManyField(
        "documents.Document", verbose_name="fichiers", blank=True, related_name="closing_deposits"
    )
    history = HistoricalRecords(m2m_fields=[documents])

    class Meta:
        verbose_name = "dépôt de l'exercice"
        verbose_name_plural = "dépôts de l'exercice"
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["year", "kind"], name="one_deposit_per_kind")
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.year.label}"
