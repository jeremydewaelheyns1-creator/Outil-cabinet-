"""Fiche client et ce qui s'y rattache directement.

Choix structurants (voir docs/DECISIONS.md) :
- le numéro d'entreprise et le numéro national sont des champs du client (uniques), car
  toutes les reprises et tous les documents officiels se rattachent par eux ;
- les relations (dirigeants, actionnaires, conjoint...) relient deux fiches clients :
  une personne n'est saisie qu'une fois, même si elle dirige plusieurs sociétés ;
- toute requête passe par `Client.objects.visible_to(user)` (droits par portefeuille).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any, ClassVar

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.core.models import Portfolio, User

from .identifiers import (
    format_enterprise_number,
    format_national_number,
    mask_national_number,
    validate_enterprise_number,
    validate_national_number,
    vat_number_from_enterprise_number,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser

PERCENT_VALIDATORS = [MinValueValidator(0), MaxValueValidator(100)]


class ClientQuerySet(models.QuerySet["Client"]):
    def visible_to(self, user: User | AnonymousUser) -> ClientQuerySet:
        return self.filter(portfolio__in=Portfolio.objects.visible_to(user))

    def active(self) -> ClientQuerySet:
        return self.filter(status=Client.Status.ACTIVE)

    def search(self, text: str) -> ClientQuerySet:
        text = text.strip()
        if not text:
            return self
        digits = "".join(c for c in text if c.isdigit())
        query = Q(name__unaccent__icontains=text) | Q(first_name__unaccent__icontains=text)
        query |= Q(reference__iexact=text)
        if len(digits) >= 4:
            query |= Q(enterprise_number__contains=digits)
        # Jamais de recherche par numéro national ici : elle passe par une recherche dédiée,
        # réservée au profil autorisé et journalisée (voir clients.views.national_number_lookup).
        parts = text.split()
        if len(parts) >= 2:
            # « Jean Dupont » ou « Dupont Jean »
            first, rest = parts[0], " ".join(parts[1:])
            query |= Q(first_name__unaccent__icontains=first, name__unaccent__icontains=rest)
            query |= Q(name__unaccent__icontains=first, first_name__unaccent__icontains=rest)
        return self.filter(query)


class Client(models.Model):
    class Kind(models.TextChoices):
        PERSON = "person", "Personne physique"
        COMPANY = "company", "Société"
        NONPROFIT = "nonprofit", "Association ou fondation"
        OTHER = "other", "Autre entité"

    class Status(models.TextChoices):
        PROSPECT = "prospect", "Prospect"
        ACTIVE = "active", "Client"
        FORMER = "former", "Ancien client"

    class Language(models.TextChoices):
        FR = "fr", "Français"
        NL = "nl", "Néerlandais"
        DE = "de", "Allemand"
        EN = "en", "Anglais"

    class VatStatus(models.TextChoices):
        UNKNOWN = "", "Non renseigné"
        SUBJECT = "subject", "Assujetti"
        SMALL_BUSINESS = "franchise", "Assujetti en franchise"
        EXEMPT = "exempt", "Assujetti exonéré (art. 44)"
        MIXED = "mixed", "Assujetti mixte"
        NOT_SUBJECT = "not_subject", "Non assujetti"

    class VatPeriodicity(models.TextChoices):
        NONE = "", "Aucune"
        MONTHLY = "monthly", "Mensuelle"
        QUARTERLY = "quarterly", "Trimestrielle"

    kind = models.CharField("type", max_length=20, choices=Kind.choices, default=Kind.COMPANY)
    status = models.CharField(
        "statut", max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    portfolio = models.ForeignKey(
        Portfolio, verbose_name="portefeuille", on_delete=models.PROTECT, related_name="clients"
    )

    name = models.CharField(
        "nom ou dénomination",
        max_length=255,
        help_text="Dénomination pour une entité, nom de famille pour une personne.",
    )
    first_name = models.CharField("prénom", max_length=150, blank=True)
    legal_form = models.CharField("forme juridique", max_length=100, blank=True)
    language = models.CharField(
        "langue", max_length=2, choices=Language.choices, default=Language.FR
    )

    # Identifiants. Chaînes vides interdites pour les champs uniques : on stocke NULL.
    enterprise_number = models.CharField(
        "numéro d'entreprise",
        max_length=10,
        unique=True,
        null=True,
        blank=True,
        validators=[validate_enterprise_number],
    )
    national_number = models.CharField(
        "numéro national",
        max_length=11,
        unique=True,
        null=True,
        blank=True,
        validators=[validate_national_number],
        help_text="Donnée sensible : masquée à l'affichage, chaque consultation est journalisée.",
    )
    reference = models.CharField(
        "référence comptable",
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        help_text="Référence du dossier dans le logiciel comptable.",
    )

    birth_date = models.DateField("date de naissance", null=True, blank=True)
    nationality = models.CharField("nationalité (code pays)", max_length=2, blank=True)

    street = models.CharField("rue", max_length=200, blank=True)
    house_number = models.CharField("numéro", max_length=20, blank=True)
    box = models.CharField("boîte", max_length=20, blank=True)
    postal_code = models.CharField("code postal", max_length=20, blank=True)
    city = models.CharField("localité", max_length=100, blank=True)
    country = models.CharField("pays (code)", max_length=2, default="BE")

    vat_status = models.CharField(
        "statut TVA", max_length=20, choices=VatStatus.choices, default="", blank=True
    )
    vat_periodicity = models.CharField(
        "périodicité TVA", max_length=20, choices=VatPeriodicity.choices, default="", blank=True
    )
    fiscal_year_end_month = models.PositiveSmallIntegerField(
        "mois de clôture",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    fiscal_year_end_day = models.PositiveSmallIntegerField(
        "jour de clôture",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
    )

    client_since = models.DateField("client depuis", null=True, blank=True)
    client_until = models.DateField("client jusqu'au", null=True, blank=True)

    # Données publiques (BCE)
    founded_on = models.DateField("date de début (BCE)", null=True, blank=True)
    bce_status = models.CharField("statut BCE", max_length=20, blank=True)
    bce_juridical_situation = models.CharField(
        "situation juridique (BCE)", max_length=100, blank=True
    )
    nace_codes = models.JSONField("activités NACE principales", default=list, blank=True)
    bce_synced_at = models.DateTimeField("dernière synchronisation BCE", null=True, blank=True)

    notes = models.TextField("notes", blank=True)
    created_at = models.DateTimeField("créé le", default=timezone.now, editable=False)
    updated_at = models.DateTimeField("modifié le", auto_now=True)

    objects = ClientQuerySet.as_manager()
    history = HistoricalRecords()

    class Meta:
        verbose_name = "client"
        verbose_name_plural = "clients"
        ordering: ClassVar = ["name", "first_name"]
        indexes: ClassVar = [models.Index(fields=["name"]), models.Index(fields=["kind", "status"])]
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=~Q(enterprise_number=""), name="client_enterprise_number_not_empty"
            ),
            models.CheckConstraint(
                condition=~Q(national_number=""), name="client_national_number_not_empty"
            ),
            models.CheckConstraint(condition=~Q(reference=""), name="client_reference_not_empty"),
        ]

    def __str__(self) -> str:
        return self.display_name

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Les champs uniques facultatifs sont stockés à NULL plutôt que vides.
        self.enterprise_number = self.enterprise_number or None
        self.national_number = self.national_number or None
        self.reference = (self.reference or "").strip() or None
        super().save(*args, **kwargs)

    def get_absolute_url(self) -> str:
        return reverse("clients:identity", args=[self.pk])

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.kind == self.Kind.PERSON:
            if not self.first_name:
                errors["first_name"] = "Le prénom est requis pour une personne physique."
        elif self.national_number:
            errors["national_number"] = "Le numéro national ne concerne que les personnes."
        if self.client_until and self.client_since and self.client_until < self.client_since:
            errors["client_until"] = "La date de fin précède la date de début."
        if self.fiscal_year_end_day and not self.fiscal_year_end_month:
            errors["fiscal_year_end_month"] = "Indiquez le mois de clôture."
        if self.fiscal_year_end_month and self.fiscal_year_end_day:
            try:
                date(2024, self.fiscal_year_end_month, self.fiscal_year_end_day)
            except ValueError:
                errors["fiscal_year_end_day"] = "Ce jour n'existe pas pour ce mois."
        if errors:
            raise ValidationError(errors)

    # --- Affichage ----------------------------------------------------------------------------

    @property
    def display_name(self) -> str:
        if self.kind == self.Kind.PERSON and self.first_name:
            return f"{self.name} {self.first_name}"
        if self.legal_form:
            return f"{self.name} {self.legal_form}"
        return self.name

    @property
    def is_person(self) -> bool:
        return self.kind == self.Kind.PERSON

    @property
    def enterprise_number_display(self) -> str:
        return format_enterprise_number(self.enterprise_number) if self.enterprise_number else ""

    @property
    def vat_number(self) -> str:
        return vat_number_from_enterprise_number(self.enterprise_number or "")

    @property
    def national_number_masked(self) -> str:
        return mask_national_number(self.national_number or "")

    @property
    def national_number_display(self) -> str:
        return format_national_number(self.national_number or "")

    @property
    def address_lines(self) -> list[str]:
        line1 = " ".join(p for p in [self.street, self.house_number] if p)
        if self.box:
            line1 = f"{line1} bte {self.box}"
        line2 = " ".join(p for p in [self.postal_code, self.city] if p)
        lines = [line for line in (line1, line2) if line]
        if self.country and self.country != "BE":
            lines.append(self.country)
        return lines

    @property
    def fiscal_year_end_display(self) -> str:
        if not self.fiscal_year_end_month:
            return ""
        day = self.fiscal_year_end_day or 31
        return f"{day:02d}/{self.fiscal_year_end_month:02d}"


def field_label(name: str) -> str:
    """Libellé d'un champ de la fiche client (« numéro d'entreprise »)."""
    return str(getattr(Client._meta.get_field(name), "verbose_name", name))


class ContactPoint(models.Model):
    class Kind(models.TextChoices):
        EMAIL = "email", "E-mail"
        PHONE = "phone", "Téléphone"
        WEBSITE = "website", "Site web"

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="contacts")
    kind = models.CharField("type", max_length=20, choices=Kind.choices)
    value = models.CharField("valeur", max_length=254)
    label = models.CharField("libellé", max_length=100, blank=True)
    is_primary = models.BooleanField("principal", default=False)
    source = models.CharField("source", max_length=20, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "coordonnée"
        verbose_name_plural = "coordonnées"
        ordering: ClassVar = ["kind", "-is_primary", "value"]
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["client", "kind", "value"], name="unique_contact_value")
        ]

    def __str__(self) -> str:
        return self.value


class RelationQuerySet(models.QuerySet["Relation"]):
    def current(self, on: date | None = None) -> RelationQuerySet:
        on = on or timezone.localdate()
        return self.filter(Q(start_date__isnull=True) | Q(start_date__lte=on)).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=on)
        )


class Relation(models.Model):
    """`person` exerce `role` dans ou auprès de `entity`.

    Exemples : Jean (person) est gérant (role) de Dupont SRL (entity) ; Holding SA (person,
    ici une entité actionnaire) détient 60 % de Dupont SRL.
    """

    class Role(models.TextChoices):
        MANAGER = "manager", "Gérant"
        DIRECTOR = "director", "Administrateur"
        MANAGING_DIRECTOR = "managing_director", "Administrateur délégué"
        SHAREHOLDER = "shareholder", "Actionnaire ou associé"
        BENEFICIAL_OWNER = "beneficial_owner", "Bénéficiaire effectif déclaré"
        PERMANENT_REPRESENTATIVE = "permanent_representative", "Représentant permanent"
        LIQUIDATOR = "liquidator", "Liquidateur"
        SPOUSE = "spouse", "Conjoint ou cohabitant légal"
        OTHER = "other", "Autre"

    MANAGEMENT_ROLES: ClassVar[tuple[str, ...]] = (
        Role.MANAGER,
        Role.DIRECTOR,
        Role.MANAGING_DIRECTOR,
        Role.LIQUIDATOR,
    )
    ROLES_WITH_PERCENTAGE: ClassVar[tuple[str, ...]] = (Role.SHAREHOLDER, Role.BENEFICIAL_OWNER)

    entity = models.ForeignKey(
        Client, verbose_name="client", on_delete=models.CASCADE, related_name="relations_as_entity"
    )
    person = models.ForeignKey(
        Client,
        verbose_name="personne ou entité liée",
        on_delete=models.PROTECT,
        related_name="relations_as_person",
    )
    role = models.CharField("rôle", max_length=30, choices=Role.choices)
    share_percentage = models.DecimalField(
        "% du capital",
        max_digits=7,
        decimal_places=4,
        null=True,
        blank=True,
        validators=PERCENT_VALIDATORS,
    )
    voting_percentage = models.DecimalField(
        "% des droits de vote",
        max_digits=7,
        decimal_places=4,
        null=True,
        blank=True,
        validators=PERCENT_VALIDATORS,
    )
    start_date = models.DateField("début", null=True, blank=True)
    end_date = models.DateField("fin", null=True, blank=True)
    notes = models.CharField("remarque", max_length=255, blank=True)
    source = models.CharField("source", max_length=20, blank=True)

    objects = RelationQuerySet.as_manager()
    history = HistoricalRecords()

    class Meta:
        verbose_name = "relation"
        verbose_name_plural = "relations"
        ordering: ClassVar = ["role", "person__name"]
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=~Q(entity=models.F("person")), name="relation_not_self"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.person} — {self.get_role_display()} — {self.entity}"

    def clean(self) -> None:
        if self.entity_id and self.entity_id == self.person_id:
            raise ValidationError("Un client ne peut pas être lié à lui-même.")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "La fin précède le début."})
        has_percentage = self.share_percentage is not None or self.voting_percentage is not None
        if has_percentage and self.role not in self.ROLES_WITH_PERCENTAGE:
            raise ValidationError(
                "Les pourcentages ne concernent que les actionnaires et bénéficiaires effectifs."
            )


class Assignment(models.Model):
    """Collaborateur du cabinet affecté à un client dans un rôle donné."""

    class Role(models.TextChoices):
        PARTNER = "partner", "Associé"
        MANAGER = "manager", "Responsable"
        ASSISTANT = "assistant", "Assistant"
        LEGAL_MANAGER = "legal_manager", "Responsable juridique"
        LEGAL_ASSISTANT = "legal_assistant", "Assistant juridique"
        SOCIAL_MANAGER = "social_manager", "Responsable social"
        SOCIAL_ASSISTANT = "social_assistant", "Assistant social"

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="assignments")
    user = models.ForeignKey(
        User, verbose_name="collaborateur", on_delete=models.PROTECT, related_name="assignments"
    )
    role = models.CharField("rôle", max_length=30, choices=Role.choices)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "affectation"
        verbose_name_plural = "affectations"
        ordering: ClassVar = ["role"]
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["client", "role"], name="unique_assignment_role")
        ]

    def __str__(self) -> str:
        return f"{self.get_role_display()} : {self.user}"
