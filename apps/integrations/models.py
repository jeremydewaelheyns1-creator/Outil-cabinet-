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
