"""Feuille de temps (D-058) : ce que chacun a fait, de quelle heure à quelle heure, et pour
quel dossier (facultatif : une formation ou une tâche interne n'a pas de dossier).

Les heures d'un employé sont des données personnelles : chacun voit les siennes ; voir celles
des collègues demande le droit « timesheet.all » et chaque consultation est journalisée.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.clients.models import Client
from apps.core.models import User

MAX_MINUTES = 14 * 60


class TimeEntry(models.Model):
    class Activity(models.TextChoices):
        VAT = "tva", "TVA"
        BOOKKEEPING = "compta", "Comptabilité et encodage"
        CLOSING = "cloture", "Clôture et comptes annuels"
        TAX = "impots", "Impôts (ISOC, IPP)"
        LEGAL = "juridique", "Juridique"
        ADVICE = "conseil", "Conseil et rendez-vous"
        SOCIAL = "social", "Social"
        ADMIN = "admin", "Administratif et anti-blanchiment"
        INTERNAL = "interne", "Interne"
        TRAINING = "formation", "Formation"
        OTHER = "autre", "Autre"

    NOT_BILLABLE: ClassVar[set[str]] = {Activity.INTERNAL, Activity.TRAINING}

    user = models.ForeignKey(
        User, verbose_name="collaborateur", on_delete=models.PROTECT, related_name="time_entries"
    )
    client = models.ForeignKey(
        Client,
        verbose_name="dossier",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="time_entries",
    )
    day = models.DateField("jour", db_index=True)
    start = models.TimeField("début")
    end = models.TimeField("fin")
    activity = models.CharField(
        "activité", max_length=20, choices=Activity.choices, default=Activity.OTHER
    )
    description = models.CharField("ce qui a été fait", max_length=200, blank=True)
    # Ajouté depuis une ligne TVA (« + Temps », D-110) : mon temps sur cette déclaration.
    vat_filing = models.ForeignKey(
        "vat.VatFiling", verbose_name="déclaration TVA", on_delete=models.SET_NULL, null=True,
        blank=True, related_name="time_entries",
    )  # fmt: skip
    billable = models.BooleanField("facturable", default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords(excluded_fields=["updated_at"])

    class Meta:
        verbose_name = "temps passé"
        verbose_name_plural = "temps passé"
        ordering: ClassVar = ["day", "start"]
        indexes: ClassVar = [models.Index(fields=["user", "day"])]

    def __str__(self) -> str:
        return f"{self.day:%d/%m/%Y} {self.start:%H:%M}-{self.end:%H:%M}"

    @property
    def minutes(self) -> int:
        return minutes_between(self.start, self.end)

    def clean(self) -> None:
        if None in (self.start, self.end, self.day):
            return  # champ manquant : déjà signalé par le formulaire
        if self.end <= self.start:
            raise ValidationError("L'heure de fin doit venir après l'heure de début.")
        if self.minutes > MAX_MINUTES:
            raise ValidationError("Une entrée ne peut pas dépasser 14 heures.")
        if self.activity in self.NOT_BILLABLE:
            self.billable = False
        if self.client_id is None:
            self.billable = False
        overlap = TimeEntry.objects.filter(
            user_id=self.user_id, day=self.day, start__lt=self.end, end__gt=self.start
        ).exclude(pk=self.pk)
        if self.user_id and overlap.exists():
            raise ValidationError("Ce créneau chevauche une autre entrée de la même journée.")


def minutes_between(start: time, end: time) -> int:
    today = date.today()
    delta = datetime.combine(today, end) - datetime.combine(today, start)
    return max(0, int(delta.total_seconds() // 60))


def hours_label(minutes: int) -> str:
    """« 1 h 30 », « 45 min », « 0 h »."""
    if minutes < 60:
        return f"{minutes} min" if minutes else "0 h"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest:02d}" if rest else f"{hours} h"
