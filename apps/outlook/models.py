"""Boîte Outlook reliée par un employé (D-044).

On garde seulement ce qu'il faut pour envoyer en son nom : son adresse et un jeton Microsoft
de renouvellement, **chiffré** (jamais son mot de passe, que l'outil ne voit pas). Le droit
accordé est « envoyer des e-mails » : l'outil ne peut pas lire sa boîte.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.core.models import User


class MailboxLink(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="mailbox")
    address = models.EmailField("adresse")
    token = models.TextField("jeton chiffré")  # voir crypto.py
    connected_at = models.DateTimeField("reliée le", default=timezone.now)
    last_used_at = models.DateTimeField("dernier envoi", null=True, blank=True)
    broken_at = models.DateTimeField(
        "à relier à nouveau depuis", null=True, blank=True,
        help_text="Microsoft a refusé le jeton (mot de passe changé, accès retiré…).",
    )  # fmt: skip

    class Meta:
        verbose_name = "boîte Outlook reliée"
        verbose_name_plural = "boîtes Outlook reliées"

    def __str__(self) -> str:
        return self.address

    @property
    def usable(self) -> bool:
        return self.broken_at is None
