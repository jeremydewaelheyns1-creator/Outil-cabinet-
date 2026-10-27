"""Échéances : une tâche datée par client (déclaration TVA, comptes annuels, ISOC…).

Les tâches récurrentes sont créées automatiquement à partir des règles de
`config/taches/regles.yaml` (voir `generator.py`). Une tâche générée est identifiée par
(client, règle, période) : la régénérer ne crée jamais de doublon. Le cabinet peut aussi créer
des tâches ponctuelles à la main.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

from django.db import models
from django.db.models import Q
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.clients.models import Client
from apps.core.models import User

MANUAL = "manual"


class TaskQuerySet(models.QuerySet["Task"]):
    def visible_to(self, user: User) -> TaskQuerySet:
        return self.filter(client__in=Client.objects.visible_to(user))

    def open(self) -> TaskQuerySet:
        return self.filter(status__in=Task.OPEN_STATUSES)

    def overdue(self, today: date | None = None) -> TaskQuerySet:
        return self.open().filter(due_date__lt=today or timezone.localdate())


class Task(models.Model):
    class Status(models.TextChoices):
        TODO = "todo", "À faire"
        IN_PROGRESS = "in_progress", "En cours"
        WAITING = "waiting", "En attente du client"
        DONE = "done", "Terminée"
        NOT_APPLICABLE = "na", "Sans objet"

    class Category(models.TextChoices):
        VAT = "tva", "TVA"
        ACCOUNTS = "comptes", "Comptes annuels"
        CORPORATE_TAX = "isoc", "Impôt des sociétés"
        PERSONAL_TAX = "ipp", "Impôt des personnes physiques"
        LEGAL = "juridique", "Juridique"
        AML = "aml", "Anti-blanchiment"
        OTHER = "autre", "Autre"

    OPEN_STATUSES: ClassVar[tuple[str, ...]] = (
        Status.TODO,
        Status.IN_PROGRESS,
        Status.WAITING,
    )

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="tasks")
    kind = models.CharField("règle", max_length=50, default=MANUAL, db_index=True)
    title = models.CharField("intitulé", max_length=200)
    category = models.CharField(
        "catégorie", max_length=20, choices=Category.choices, default=Category.OTHER
    )
    period_key = models.CharField("période (code)", max_length=30, blank=True)
    period_label = models.CharField("période", max_length=60, blank=True)
    period_start = models.DateField("début de période", null=True, blank=True)
    period_end = models.DateField("fin de période", null=True, blank=True)
    due_date = models.DateField("échéance", db_index=True)
    status = models.CharField(
        "statut", max_length=20, choices=Status.choices, default=Status.TODO, db_index=True
    )
    assignee = models.ForeignKey(
        User,
        verbose_name="responsable",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    generated = models.BooleanField("créée automatiquement", default=False)
    # D-061 : échéance à une heure précise (rendez-vous…), affichée dans « Mon agenda ».
    due_time = models.TimeField("heure", null=True, blank=True)
    end_time = models.TimeField("jusqu'à", null=True, blank=True)
    remind = models.BooleanField("me rappeler le jour J", default=False)
    reminded_at = models.DateTimeField("rappel envoyé le", null=True, blank=True)
    notes = models.TextField("remarques", blank=True)
    completed_at = models.DateTimeField("terminée le", null=True, blank=True)
    completed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField("créée le", default=timezone.now, editable=False)
    updated_at = models.DateTimeField("modifiée le", auto_now=True)

    objects = TaskQuerySet.as_manager()
    history = HistoricalRecords(excluded_fields=["updated_at"])

    class Meta:
        verbose_name = "échéance"
        verbose_name_plural = "échéances"
        ordering: ClassVar = ["due_date", "client__name"]
        indexes: ClassVar = [
            models.Index(fields=["status", "due_date"]),
            models.Index(fields=["assignee", "status"]),
        ]
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["client", "kind", "period_key"],
                condition=Q(generated=True),
                name="unique_generated_task_per_period",
            )
        ]

    def __str__(self) -> str:
        return f"{self.title} — {self.client}"

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN_STATUSES

    @property
    def days_left(self) -> int:
        return (self.due_date - timezone.localdate()).days

    @property
    def is_overdue(self) -> bool:
        return self.is_open and self.days_left < 0

    @property
    def urgency(self) -> str:
        """Pour l'affichage : en retard, cette semaine, bientôt, plus tard, clôturée."""
        if not self.is_open:
            return "closed"
        if self.days_left < 0:
            return "overdue"
        if self.days_left <= 7:
            return "week"
        if self.days_left <= 30:
            return "soon"
        return "later"

    @property
    def delay_label(self) -> str:
        if not self.is_open:
            return self.get_status_display().lower()
        days = self.days_left
        if days < 0:
            return f"en retard de {-days} j"
        if days == 0:
            return "aujourd'hui"
        if days == 1:
            return "demain"
        return f"dans {days} j"

    @property
    def progress(self) -> tuple[int, int]:
        """(étapes faites, étapes au total), sur les étapes préchargées."""
        steps = list(self.steps.all())
        return sum(1 for s in steps if s.done), len(steps)

    # Où l'on travaille vraiment cette échéance (le reste : la liste des échéances du dossier).
    WORK_PAGES: ClassVar[dict[str, str]] = {
        "tva_mensuelle": "clients:vat",
        "tva_trimestrielle": "clients:vat",
    }

    @property
    def work_url(self) -> str:
        from django.urls import reverse

        return reverse(self.WORK_PAGES.get(self.kind, "clients:tasks"), args=[self.client_id])

    @property
    def is_untouched(self) -> bool:
        """Tâche générée que personne n'a encore travaillée : peut être retirée sans perte."""
        return (
            self.generated
            and self.status == self.Status.TODO
            and not self.notes
            and not self.steps.filter(done=True).exists()
        )


class TaskStep(models.Model):
    """Étape d'une check-list (« encodage », « contrôle », « envoi »…)."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="steps")
    label = models.CharField("étape", max_length=200)
    position = models.PositiveSmallIntegerField("ordre", default=0)
    done = models.BooleanField("faite", default=False)
    done_at = models.DateTimeField("faite le", null=True, blank=True)
    done_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "étape"
        verbose_name_plural = "étapes"
        ordering: ClassVar = ["position", "pk"]

    def __str__(self) -> str:
        return self.label


class GenerationRun(models.Model):
    """Trace des générations automatiques (une par jour au plus via `run_jobs`)."""

    started_at = models.DateTimeField("début", default=timezone.now)
    finished_at = models.DateTimeField("fin", null=True, blank=True)
    created = models.PositiveIntegerField("tâches créées", default=0)
    removed = models.PositiveIntegerField("tâches retirées", default=0)
    clients = models.PositiveIntegerField("clients traités", default=0)
    # Empreinte du fichier de règles : s'il change (nouvelle date légale), on régénère le jour même.
    rules_hash = models.CharField("empreinte des règles", max_length=64, blank=True)

    class Meta:
        verbose_name = "génération d'échéances"
        verbose_name_plural = "générations d'échéances"
        ordering: ClassVar = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.started_at:%d/%m/%Y %H:%M} : {self.created} créées"


# --- Prolongations de délai décidées par le SPF Finances (D-089) ------------------------------


class DeadlineNotice(models.Model):
    """Article d'une source officielle qui parle peut-être d'un délai prolongé : à vérifier.

    Repéré par des mots (« prolongation », « délai »… + « TVA », « déclaration »…), jamais
    appliqué tel quel : un administrateur le lit et encode la prolongation, ou l'écarte.
    """

    class Status(models.TextChoices):
        NEW = "new", "À vérifier"
        DISMISSED = "dismissed", "Pas une prolongation"
        HANDLED = "handled", "Prolongation encodée"

    source = models.CharField("source", max_length=80)
    url = models.URLField("lien", max_length=500, unique=True)
    title = models.CharField("titre", max_length=300)
    excerpt = models.TextField("extrait", blank=True)
    published_at = models.DateTimeField("publié le", null=True, blank=True)
    found_at = models.DateTimeField("repéré le", default=timezone.now)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW)
    handled_at = models.DateTimeField(null=True, blank=True)
    handled_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "article à vérifier (délais du SPF)"
        verbose_name_plural = "articles à vérifier (délais du SPF)"
        ordering: ClassVar = ["-published_at", "-found_at"]

    def __str__(self) -> str:
        return self.title


class DeadlineExtension(models.Model):
    """Délai prolongé, confirmé par un administrateur : les échéances concernées sont déplacées
    et chacun voit un petit message à sa prochaine ouverture de l'outil."""

    kind = models.CharField("échéance", max_length=60)  # code de règle (regles.yaml)
    period_key = models.CharField("période", max_length=20)
    label = models.CharField("intitulé", max_length=200)  # « Déclaration TVA 3e trimestre 2026 »
    previous_date = models.DateField("date limite d'avant")
    new_date = models.DateField("nouvelle date limite")
    note = models.CharField("précision", max_length=300, blank=True)
    source_url = models.URLField("source", max_length=500, blank=True)
    notice = models.ForeignKey(
        DeadlineNotice, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    seen_by = models.ManyToManyField(User, blank=True, related_name="+")

    class Meta:
        verbose_name = "prolongation de délai"
        verbose_name_plural = "prolongations de délai"
        ordering: ClassVar = ["-created_at"]
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["kind", "period_key", "previous_date"], name="one_extension_per_deadline"
            )
        ]

    def __str__(self) -> str:
        return f"{self.label} : {self.previous_date:%d/%m/%Y} → {self.new_date:%d/%m/%Y}"
