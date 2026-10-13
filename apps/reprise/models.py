"""Suivi des imports de reprise : chaque fichier est d'abord analysé, puis importé."""

from datetime import timedelta
from typing import ClassVar

from django.db import models
from django.utils import timezone

from apps.core.models import User

# Un fichier déposé mais ni importé ni abandonné est effacé après ce délai.
UPLOAD_RETENTION = timedelta(hours=24)


class ImportBatch(models.Model):
    class Kind(models.TextChoices):
        CLIENTS = "clients", "Clients (export FID-Manager)"

    class Status(models.TextChoices):
        ANALYSED = "analysed", "Analysé, en attente de confirmation"
        APPLIED = "applied", "Importé"
        DISCARDED = "discarded", "Abandonné"
        EXPIRED = "expired", "Expiré (fichier effacé)"

    kind = models.CharField("type", max_length=20, choices=Kind.choices, default=Kind.CLIENTS)
    file_name = models.CharField("fichier", max_length=255)
    # Contenu du fichier, gardé en base (et non sur le disque de l'instance Cloud Run, qui peut
    # changer entre l'analyse et la confirmation) puis effacé dès l'import ou l'abandon.
    content = models.BinaryField("contenu du fichier", null=True, editable=False)
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

    class Meta:
        verbose_name = "import de reprise"
        verbose_name_plural = "imports de reprise"
        ordering: ClassVar = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.file_name} ({self.get_status_display()})"

    @property
    def has_content(self) -> bool:
        return self.content is not None

    def close(self, status: str) -> None:
        self.content = None
        self.status = status
        self.save()


def purge_stale_uploads() -> int:
    """Efface les fichiers déposés depuis plus de 24 heures sans suite."""
    limit = timezone.now() - UPLOAD_RETENTION
    return ImportBatch.objects.filter(
        status=ImportBatch.Status.ANALYSED, created_at__lt=limit
    ).update(content=None, status=ImportBatch.Status.EXPIRED)
