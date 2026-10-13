"""Socle commun : utilisateurs, profils de sécurité, portefeuilles, journaux.

Deux journaux distincts :
- `AccessLog` : qui a consulté ou modifié quoi (exigence de traçabilité AML et RGPD).
  Il est protégé contre toute modification ou suppression par un déclencheur PostgreSQL.
- `Event` : les faits métier (document reçu, client créé, échéance proche...) que les
  automatismes traitent. Chaque traitement est mémorisé (`EventHandling`), ce qui permet de
  rejouer un événement sans jamais exécuter deux fois le même traitement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q, QuerySet
from django.utils import timezone
from simple_history.models import HistoricalRecords

from .capabilities import Capability

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser


# --- Profils de sécurité et utilisateurs ------------------------------------------------------


class SecurityProfile(models.Model):
    name = models.CharField("nom", max_length=100, unique=True)
    description = models.TextField("description", blank=True)
    capabilities = ArrayField(
        models.CharField(max_length=50, choices=Capability.choices),
        verbose_name="droits",
        default=list,
        blank=True,
    )
    history = HistoricalRecords()

    class Meta:
        verbose_name = "profil de sécurité"
        verbose_name_plural = "profils de sécurité"
        ordering: ClassVar = ["name"]

    def __str__(self) -> str:
        return self.name


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def create_user(self, email: str, password: str | None = None, **extra: Any) -> User:
        if not email:
            raise ValueError("Une adresse e-mail est obligatoire.")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **extra: Any) -> User:
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField("adresse e-mail", unique=True)
    first_name = models.CharField("prénom", max_length=100, blank=True)
    last_name = models.CharField("nom", max_length=100, blank=True)
    initials = models.CharField(
        "initiales",
        max_length=10,
        blank=True,
        help_text="Utilisées dans les grilles et pour la reprise des affectations FID-Manager.",
    )
    profile = models.ForeignKey(
        SecurityProfile,
        verbose_name="profil de sécurité",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
    )
    is_active = models.BooleanField("actif", default=True)
    is_staff = models.BooleanField(
        "accès à l'administration",
        default=False,
        help_text="Permet d'ouvrir l'écran d'administration (paramétrage).",
    )
    date_joined = models.DateTimeField("créé le", default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    history = HistoricalRecords(excluded_fields=["password", "last_login"])

    class Meta:
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"
        ordering: ClassVar = ["last_name", "first_name", "email"]

    def __str__(self) -> str:
        return self.get_full_name() or self.email

    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self) -> str:
        return self.initials or self.first_name or self.email

    def has_capability(self, capability: Capability | str) -> bool:
        if not self.is_active:
            return False
        if self.is_superuser:
            return True
        return self.profile is not None and str(capability) in self.profile.capabilities


# --- Portefeuilles ----------------------------------------------------------------------------


class PortfolioQuerySet(models.QuerySet["Portfolio"]):
    def visible_to(self, user: User | AnonymousUser) -> PortfolioQuerySet:
        """Portefeuilles qu'un utilisateur a le droit de voir.

        Toute requête sur des données clients DOIT passer par ce filtre (voir CONVENTIONS).
        """
        if not user.is_authenticated or not user.is_active:
            return self.none()
        if user.is_superuser:
            return self.all()
        return self.filter(Q(is_private=False) | Q(members=user)).distinct()


class Portfolio(models.Model):
    name = models.CharField("nom", max_length=100, unique=True)
    is_private = models.BooleanField(
        "privé",
        default=False,
        help_text="Un portefeuille privé n'est visible que par ses membres.",
    )
    members = models.ManyToManyField(
        User, verbose_name="membres", blank=True, related_name="portfolios"
    )
    order = models.PositiveSmallIntegerField("ordre d'affichage", default=0)

    objects = PortfolioQuerySet.as_manager()
    history = HistoricalRecords(m2m_fields=[members])

    class Meta:
        verbose_name = "portefeuille"
        verbose_name_plural = "portefeuilles"
        ordering: ClassVar = ["order", "name"]

    def __str__(self) -> str:
        return self.name


# --- Journal des consultations ----------------------------------------------------------------


class AccessLog(models.Model):
    """Trace inaltérable de chaque consultation ou modification sensible."""

    class Action(models.TextChoices):
        VIEW = "view", "Consultation"
        CREATE = "create", "Création"
        UPDATE = "update", "Modification"
        DELETE = "delete", "Suppression"
        EXPORT = "export", "Export"
        REVEAL = "reveal", "Affichage d'une donnée sensible"
        IMPORT = "import", "Import"
        LOGIN = "login", "Connexion"
        LOGIN_FAILED = "login_failed", "Échec de connexion"
        LOGOUT = "logout", "Déconnexion"

    at = models.DateTimeField("date", default=timezone.now, db_index=True)
    # PROTECT : un compte qui apparaît dans le journal ne peut pas être supprimé, seulement
    # désactivé. Le journal reste ainsi complet et lisible.
    user = models.ForeignKey(
        User, verbose_name="utilisateur", on_delete=models.PROTECT, null=True, blank=True
    )
    user_email = models.CharField("e-mail de l'utilisateur", max_length=254, blank=True)
    action = models.CharField("action", max_length=20, choices=Action.choices)
    object_type = models.CharField("type d'objet", max_length=100, blank=True, db_index=True)
    object_id = models.CharField("identifiant de l'objet", max_length=64, blank=True)
    object_repr = models.CharField("objet", max_length=255, blank=True)
    ip_address = models.GenericIPAddressField("adresse IP", null=True, blank=True)
    details = models.JSONField("détails", default=dict, blank=True, encoder=DjangoJSONEncoder)

    class Meta:
        verbose_name = "entrée du journal des consultations"
        verbose_name_plural = "journal des consultations"
        ordering: ClassVar = ["-at"]
        indexes: ClassVar = [models.Index(fields=["object_type", "object_id", "-at"])]

    def __str__(self) -> str:
        return f"{self.at:%d/%m/%Y %H:%M} {self.user_email} {self.get_action_display()}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise PermissionError("Le journal des consultations ne peut pas être modifié.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise PermissionError("Le journal des consultations ne peut pas être supprimé.")


# --- Journal des événements -------------------------------------------------------------------


class Event(models.Model):
    """Un fait métier, enregistré une fois, traité par les automatismes abonnés."""

    class Status(models.TextChoices):
        PENDING = "pending", "À traiter"
        PROCESSED = "processed", "Traité"
        FAILED = "failed", "En échec"

    type = models.CharField("type", max_length=100, db_index=True)
    occurred_at = models.DateTimeField("date", default=timezone.now, db_index=True)
    actor = models.ForeignKey(
        User, verbose_name="auteur", on_delete=models.SET_NULL, null=True, blank=True
    )
    subject_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, null=True, blank=True)
    subject_id = models.CharField(max_length=64, blank=True)
    payload = models.JSONField("données", default=dict, blank=True, encoder=DjangoJSONEncoder)
    idempotency_key = models.CharField(
        "clé d'unicité",
        max_length=200,
        unique=True,
        null=True,
        blank=True,
        help_text="Empêche d'enregistrer deux fois le même fait (ex. le même e-mail reçu).",
    )
    status = models.CharField(
        "statut", max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    processed_at = models.DateTimeField("traité le", null=True, blank=True)

    class Meta:
        verbose_name = "événement"
        verbose_name_plural = "journal des événements"
        ordering: ClassVar = ["-occurred_at"]
        indexes: ClassVar = [models.Index(fields=["subject_type", "subject_id"])]

    def __str__(self) -> str:
        return f"{self.type} #{self.pk}"


class EventHandling(models.Model):
    """Résultat d'un traitement (handler) pour un événement : garantit l'exécution unique."""

    class Status(models.TextChoices):
        DONE = "done", "Terminé"
        FAILED = "failed", "En échec"

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="handlings")
    handler = models.CharField("traitement", max_length=200)
    status = models.CharField("statut", max_length=20, choices=Status.choices)
    attempts = models.PositiveSmallIntegerField("tentatives", default=0)
    last_error = models.TextField("dernière erreur", blank=True)
    finished_at = models.DateTimeField("terminé le", null=True, blank=True)

    class Meta:
        verbose_name = "traitement d'événement"
        verbose_name_plural = "traitements d'événements"
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["event", "handler"], name="unique_event_handler")
        ]

    def __str__(self) -> str:
        return f"{self.handler} → {self.get_status_display()}"


def events_for(obj: models.Model) -> QuerySet[Event]:
    ct = ContentType.objects.get_for_model(obj)
    return Event.objects.filter(subject_type=ct, subject_id=str(obj.pk))
