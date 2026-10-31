"""Journal des appels à l'assistant IA (D-121) : qui, quoi, combien — jamais le contenu."""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.clients.models import Client
from apps.core.models import User


class AiCall(models.Model):
    feature = models.CharField("fonction", max_length=40)
    client = models.ForeignKey(
        Client, verbose_name="dossier", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )  # fmt: skip
    user = models.ForeignKey(
        User, verbose_name="demandé par", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )  # fmt: skip
    model = models.CharField("modèle", max_length=60)
    tokens_in = models.PositiveIntegerField("mots envoyés (jetons)", default=0)
    tokens_out = models.PositiveIntegerField("mots reçus (jetons)", default=0)
    cost_eur = models.DecimalField("coût estimé (€)", max_digits=8, decimal_places=4, default=0)
    ok = models.BooleanField("réussi", default=False)
    error = models.CharField("erreur", max_length=200, blank=True)  # jamais de contenu
    created_at = models.DateTimeField("le", default=timezone.now)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "appel à l'assistant IA"
        verbose_name_plural = "appels à l'assistant IA"

    def __str__(self) -> str:
        return f"{self.feature} · {self.created_at:%d/%m/%Y %H:%M}"
