"""Suivi des imports de reprise : chaque fichier est d'abord analysé, puis importé."""

from typing import ClassVar

from django.db import models
from django.utils import timezone

from apps.core.models import User


class ImportBatch(models.Model):
    class Kind(models.TextChoices):
        CLIENTS = "clients", "Clients (export FID-Manager)"

    class Status(models.TextChoices):
        ANALYSED = "analysed", "Analysé, en attente de confirmation"
        APPLIED = "applied", "Importé"
        DISCARDED = "discarded", "Abandonné"
        FAILED = "failed", "Échoué"

    kind = models.CharField("type", max_length=20, choices=Kind.choices, default=Kind.CLIENTS)
    file_name = models.CharField("fichier", max_length=255)
    # Fichier conservé uniquement entre l'analyse et l'import, puis supprimé.
    stored_file = models.FileField("fichier déposé", upload_to="reprise/", blank=True)
    uploaded_by = models.ForeignKey(
        User, verbose_name="déposé par", on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField("déposé le", default=timezone.now)
    applied_at = models.DateTimeField("importé le", null=True, blank=True)
    status = models.CharField(
        "statut", max_length=20, choices=Status.choices, default=Status.ANALYSED
    )
    analysis = models.JSONField("rapport d'analyse", default=dict, blank=True)
    result = models.JSONField("rapport d'import", default=dict, blank=True)
    error = models.TextField("erreur", blank=True)

    class Meta:
        verbose_name = "import de reprise"
        verbose_name_plural = "imports de reprise"
        ordering: ClassVar = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.file_name} ({self.get_status_display()})"

    def discard_file(self) -> None:
        if self.stored_file:
            self.stored_file.delete(save=False)
            self.stored_file = ""
