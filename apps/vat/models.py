"""Déclarations TVA : la grille de l'onglet « Déclaration TVA », comme FID-Manager (D-040).

Une ligne (`VatFiling`) par période déclarée (mois ou trimestre). Chaque ligne a cinq cases
de suivi (`VatCell`) : documents reçus, travail fini, déclaration déposée, listing
intracommunautaire, communication au client. Chaque case a un état (sept états, comme FID),
une date, l'auteur et une remarque.

« Jamais nécessaire pour ce client » vaut pour toute une colonne d'un client (`VatNever`) :
la case est alors grisée sur toutes les périodes.
"""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.clients.models import Client
from apps.core.models import User
from apps.documents.models import Document
from apps.tasks.models import Task


class Column(models.TextChoices):
    DOCS = "docs", "Documents reçus"
    DONE = "done", "Travail fini"
    FILED = "filed", "Déclaration déposée"
    IC = "ic", "Listing intracommunautaire"
    CLIENT = "client", "Communication au client"


# Titre court affiché en tête de colonne (comme FID).
COLUMN_HEADERS = {
    Column.DOCS: "Doc. reçus",
    Column.DONE: "Fini",
    Column.FILED: "Déposée",
    Column.IC: "IC",
    Column.CLIENT: "Com. client",
}


class Status(models.TextChoices):
    NEVER = "never", "Jamais nécessaire pour ce client"
    TODO = "todo", "Non commencé"
    IN_PROGRESS = "in_progress", "Travail en cours"
    DONE = "done", "Fini"
    NOT_NEEDED = "na", "Pas nécessaire pour cette période"
    WAITING = "waiting", "En attente"
    WARNING = "warning", "Avertissement"


FINISHED = (Status.DONE, Status.NOT_NEEDED, Status.NEVER)


class VatFilingQuerySet(models.QuerySet["VatFiling"]):
    def visible_to(self, user: User) -> VatFilingQuerySet:
        return self.filter(client__in=Client.objects.visible_to(user))


class VatFiling(models.Model):
    """Une déclaration périodique d'un client (une ligne de la grille)."""

    class Periodicity(models.TextChoices):
        MONTHLY = "monthly", "Mensuelle"
        QUARTERLY = "quarterly", "Trimestrielle"

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="vat_filings")
    task = models.OneToOneField(
        Task, on_delete=models.SET_NULL, null=True, blank=True, related_name="vat_filing"
    )
    period_key = models.CharField("période (code)", max_length=10)  # 2026-T3 ou 2026-09
    period_label = models.CharField("période", max_length=40)
    period_start = models.DateField("début de période")
    period_end = models.DateField("fin de période")
    periodicity = models.CharField("périodicité", max_length=10, choices=Periodicity.choices)
    due_date = models.DateField("échéance", null=True, blank=True)
    grid_71 = models.DecimalField(
        "grille 71 (à payer)", max_digits=14, decimal_places=2, null=True, blank=True
    )
    grid_72 = models.DecimalField(
        "grille 72 (à récupérer)", max_digits=14, decimal_places=2, null=True, blank=True
    )
    advance_1 = models.DecimalField(
        "acompte payé le 1er mois", max_digits=14, decimal_places=2, null=True, blank=True
    )
    advance_2 = models.DecimalField(
        "acompte payé le 2e mois", max_digits=14, decimal_places=2, null=True, blank=True
    )
    manager = models.ForeignKey(
        User, verbose_name="responsable", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )  # fmt: skip
    assistant = models.ForeignKey(
        User, verbose_name="assistant", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )  # fmt: skip
    remark = models.TextField("remarque", blank=True)
    # Lus sur le PDF de la déclaration quand ils y sont (D-043), repris dans l'e-mail au client.
    payment_iban = models.CharField("compte de paiement", max_length=42, blank=True)
    payment_reference = models.CharField("communication structurée", max_length=24, blank=True)
    payment_bic = models.CharField("BIC", max_length=11, blank=True)
    payment_beneficiary = models.CharField("bénéficiaire du paiement", max_length=40, blank=True)
    xml = models.ForeignKey(
        Document, verbose_name="déclaration (XML)", on_delete=models.SET_NULL, null=True,
        blank=True, related_name="+",
    )  # fmt: skip
    pdf = models.ForeignKey(
        Document, verbose_name="déclaration (PDF)", on_delete=models.SET_NULL, null=True,
        blank=True, related_name="+",
    )  # fmt: skip
    ic_xml = models.ForeignKey(
        Document, verbose_name="listing IC (XML)", on_delete=models.SET_NULL, null=True,
        blank=True, related_name="+",
    )  # fmt: skip
    ic_pdf = models.ForeignKey(
        Document, verbose_name="listing IC (PDF)", on_delete=models.SET_NULL, null=True,
        blank=True, related_name="+",
    )  # fmt: skip
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    objects = VatFilingQuerySet.as_manager()
    history = HistoricalRecords()

    class Meta:
        verbose_name = "déclaration TVA"
        verbose_name_plural = "déclarations TVA"
        ordering: ClassVar = ["-period_start"]
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["client", "period_key"], name="one_vat_filing_per_period"
            )
        ]

    def __str__(self) -> str:
        return f"TVA {self.period_label} — {self.client}"

    @property
    def short_label(self) -> str:
        """« T3 2026 » ou « 09/2026 »."""
        year, _, part = self.period_key.partition("-")
        return f"{part} {year}" if part.startswith("T") else f"{part}/{year}"

    @property
    def advances_total(self) -> Decimal | None:
        """Acomptes déjà payés par le client pour ce trimestre."""
        if self.advance_1 is None and self.advance_2 is None:
            return None
        return (self.advance_1 or Decimal("0")) + (self.advance_2 or Decimal("0"))

    @property
    def remaining(self) -> Decimal | None:
        """Reste à payer après les acomptes (négatif : à récupérer). Sans montant : None."""
        if self.grid_71 is None and self.grid_72 is None:
            return None
        due = (self.grid_71 or Decimal("0")) - (self.grid_72 or Decimal("0"))
        return due - (self.advances_total or Decimal("0"))

    @property
    def balance(self) -> tuple[str, Decimal] | None:
        """Solde de la déclaration : grille 71 (à payer) ou 72 (à récupérer)."""
        if self.grid_71:
            return "71", self.grid_71
        if self.grid_72:
            return "72", self.grid_72
        if self.grid_71 is not None or self.grid_72 is not None:
            return "71", Decimal("0.00")
        return None


class VatCell(models.Model):
    """Une case de suivi d'une ligne : état, date, auteur, remarque."""

    filing = models.ForeignKey(VatFiling, on_delete=models.CASCADE, related_name="cells")
    column = models.CharField("colonne", max_length=10, choices=Column.choices)
    status = models.CharField("état", max_length=12, choices=Status.choices, default=Status.TODO)
    on = models.DateField("date", null=True, blank=True)
    by = models.ForeignKey(
        User, verbose_name="par", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )  # fmt: skip
    comment = models.CharField("remarque", max_length=300, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "case de suivi TVA"
        verbose_name_plural = "cases de suivi TVA"
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["filing", "column"], name="one_vat_cell_per_column")
        ]

    def __str__(self) -> str:
        return f"{self.get_column_display()} : {self.get_status_display()}"


class VatNever(models.Model):
    """Colonne « jamais nécessaire » pour ce client (ex. : pas d'opérations intracom)."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="vat_never")
    column = models.CharField("colonne", max_length=10, choices=Column.choices)

    class Meta:
        verbose_name = "colonne TVA jamais nécessaire"
        verbose_name_plural = "colonnes TVA jamais nécessaires"
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["client", "column"], name="one_vat_never_per_column")
        ]

    def __str__(self) -> str:
        return f"{self.client} : {self.get_column_display()}"


class VatPending(models.Model):
    """PDF reconnu pour un client mais pas avec certitude pour une période : à confirmer."""

    document = models.OneToOneField(Document, on_delete=models.CASCADE, related_name="vat_pending")
    kind = models.CharField("sorte", max_length=5)  # vat / ic (voir intervat.py)
    period_key = models.CharField("période proposée", max_length=10, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = "déclaration TVA à confirmer"
        verbose_name_plural = "déclarations TVA à confirmer"
        ordering: ClassVar = ["created_at"]

    def __str__(self) -> str:
        return str(self.document)


class VatMessage(models.Model):
    """E-mail au client après le dépôt (D-042) : préparé par l'outil, relu, puis envoyé.

    Tant que la messagerie du cabinet n'est pas branchée, « Envoyer » l'enregistre comme prêt
    à partir (`delivered` reste faux) et coche la case « Com. client ».
    """

    filing = models.ForeignKey(VatFiling, on_delete=models.CASCADE, related_name="messages")
    to = models.EmailField("à", blank=True)
    subject = models.CharField("objet", max_length=255)
    body = models.TextField("message")
    attach_pdf = models.BooleanField("joindre le PDF de la déclaration", default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    sent_at = models.DateTimeField("envoyé le", null=True, blank=True)
    sent_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    delivered = models.BooleanField("parti réellement", default=False)
    sent_from = models.EmailField("envoyé depuis", blank=True)  # boîte Outlook (D-044)

    class Meta:
        verbose_name = "e-mail TVA au client"
        verbose_name_plural = "e-mails TVA au client"
        ordering: ClassVar = ["-created_at"]

    def __str__(self) -> str:
        return self.subject
