"""Traces des consultations de services externes (preuves en cas de contrôle)."""

from typing import ClassVar

from django.db import models
from django.utils import timezone

from apps.clients.models import Client
from apps.core.models import User


class VatCheck(models.Model):
    """Résultat d'une vérification d'un numéro de TVA dans VIES (Commission européenne).

    Conservé tel quel : avec un identifiant de consultation, il prouve qu'on a vérifié le
    numéro du client à une date donnée (livraisons intracommunautaires).
    """

    class Result(models.TextChoices):
        VALID = "valid", "Valide"
        INVALID = "invalid", "Non valide"
        UNAVAILABLE = "unavailable", "Service indisponible"

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, null=True, blank=True, related_name="vat_checks"
    )
    country_code = models.CharField("pays", max_length=2)
    vat_number = models.CharField("numéro", max_length=20)
    result = models.CharField("résultat", max_length=20, choices=Result.choices)
    name = models.CharField("nom renvoyé", max_length=255, blank=True)
    address = models.TextField("adresse renvoyée", blank=True)
    request_identifier = models.CharField("identifiant de consultation", max_length=100, blank=True)
    error_code = models.CharField("code d'erreur", max_length=50, blank=True)
    checked_at = models.DateTimeField("vérifié le", default=timezone.now)
    checked_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    raw = models.JSONField("réponse brute", default=dict, blank=True)

    class Meta:
        verbose_name = "vérification TVA (VIES)"
        verbose_name_plural = "vérifications TVA (VIES)"
        ordering: ClassVar = ["-checked_at"]

    def __str__(self) -> str:
        return f"{self.country_code}{self.vat_number} : {self.get_result_display()}"


class OfficialSnapshot(models.Model):
    """Relevé d'un site officiel pour un client : ce qu'on y a lu, à quelle date.

    On garde les derniers relevés pour repérer ce qui change (nouvelle publication au
    Moniteur, nouvel administrateur, nouveaux comptes annuels).
    """

    class Source(models.TextChoices):
        KBO = "kbo", "BCE (fonctions)"
        MONITEUR = "moniteur", "Moniteur belge"
        NBB = "nbb", "Banque Nationale (comptes annuels)"

    class Status(models.TextChoices):
        OK = "ok", "Lu"
        UNAVAILABLE = "unavailable", "Site injoignable"
        NOT_CONFIGURED = "not_configured", "Accès non configuré"
        UNREADABLE = "unreadable", "Page illisible"

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="official_snapshots")
    source = models.CharField("source", max_length=20, choices=Source.choices)
    status = models.CharField("état", max_length=20, choices=Status.choices)
    items = models.JSONField("éléments lus", default=list, blank=True)
    error = models.CharField("erreur", max_length=200, blank=True)
    fetched_at = models.DateTimeField("consulté le", default=timezone.now)
    fetched_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "relevé d'un site officiel"
        verbose_name_plural = "relevés des sites officiels"
        ordering: ClassVar = ["-fetched_at"]
        indexes: ClassVar = [models.Index(fields=["client", "source", "-fetched_at"])]

    def __str__(self) -> str:
        return f"{self.get_source_display()} · {self.client_id} · {self.fetched_at:%d/%m/%Y}"

    @property
    def ok(self) -> bool:
        return self.status == self.Status.OK
