"""Boîte Outlook reliée par un employé (D-044).

On garde seulement ce qu'il faut pour envoyer en son nom : son adresse et un jeton Microsoft
de renouvellement, **chiffré** (jamais son mot de passe, que l'outil ne voit pas). Le droit
accordé est « envoyer des e-mails » ; la lecture de la boîte (D-060) n'est possible que si
l'employé l'active lui-même, ce qui demande à Microsoft un droit de plus (« Mail.Read »).
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
    # D-060 : lecture de la boîte, activée par l'employé lui-même (droit « Mail.Read »).
    scopes = models.CharField("droits accordés", max_length=200, blank=True)
    read_enabled = models.BooleanField("lecture de la boîte activée", default=False)
    read_since = models.DateTimeField("lecture depuis", null=True, blank=True)
    inbox_cursor = models.DateTimeField("réception lue jusqu'au", null=True, blank=True)
    sent_cursor = models.DateTimeField("envoyés lus jusqu'au", null=True, blank=True)
    last_sync_at = models.DateTimeField("dernière lecture", null=True, blank=True)
    sync_error = models.CharField("dernière erreur de lecture", max_length=200, blank=True)

    class Meta:
        verbose_name = "boîte Outlook reliée"
        verbose_name_plural = "boîtes Outlook reliées"

    def __str__(self) -> str:
        return self.address

    @property
    def usable(self) -> bool:
        return self.broken_at is None
