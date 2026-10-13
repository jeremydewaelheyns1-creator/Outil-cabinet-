"""Copie locale des données ouvertes de la Banque-Carrefour des Entreprises (BCE).

Source : fichiers « KBO Open Data » du SPF Économie (export complet mensuel, mises à jour
quotidiennes). On n'importe que ce qui sert au cabinet, pour garder une base légère :
- les entreprises (pas les unités d'établissement) ;
- toutes leurs dénominations et adresses ;
- leurs activités principales (classification MAIN) ;
- leurs coordonnées publiques ;
- les libellés des codes (français, à défaut néerlandais).

Ces tables sont remplacées par chaque import : on n'y écrit jamais à la main.
"""

from __future__ import annotations

from typing import ClassVar

from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone


class Enterprise(models.Model):
    class Type(models.TextChoices):
        PERSON = "1", "Personne physique"
        LEGAL = "2", "Personne morale"

    number = models.CharField("numéro", max_length=10, primary_key=True)
    status = models.CharField("statut", max_length=10)
    juridical_situation = models.CharField("situation juridique", max_length=10)
    type_of_enterprise = models.CharField("type", max_length=1, choices=Type.choices)
    juridical_form = models.CharField("forme juridique", max_length=10, blank=True)
    juridical_form_cac = models.CharField("forme juridique (CSA)", max_length=10, blank=True)
    start_date = models.DateField("date de début", null=True, blank=True)

    class Meta:
        verbose_name = "entreprise (BCE)"
        verbose_name_plural = "entreprises (BCE)"

    def __str__(self) -> str:
        return self.number


class Denomination(models.Model):
    class Type(models.TextChoices):
        LEGAL = "001", "Dénomination"
        ABBREVIATION = "002", "Abréviation"
        COMMERCIAL = "003", "Dénomination commerciale"

    entity_number = models.CharField(max_length=10, db_index=True)
    language = models.CharField(max_length=2)
    type = models.CharField(max_length=10, choices=Type.choices)
    name = models.TextField()
    # Nom en minuscules sans accents, indexé en trigrammes pour la recherche « contient ».
    search_name = models.TextField()

    class Meta:
        verbose_name = "dénomination (BCE)"
        verbose_name_plural = "dénominations (BCE)"
        indexes: ClassVar = [
            GinIndex(
                fields=["search_name"], name="bce_denomination_trgm", opclasses=["gin_trgm_ops"]
            )
        ]

    def __str__(self) -> str:
        return self.name


class Address(models.Model):
    entity_number = models.CharField(max_length=10, db_index=True)
    type_of_address = models.CharField(max_length=10)
    country_nl = models.TextField(blank=True)
    country_fr = models.TextField(blank=True)
    zipcode = models.TextField(blank=True)
    municipality_nl = models.TextField(blank=True)
    municipality_fr = models.TextField(blank=True)
    street_nl = models.TextField(blank=True)
    street_fr = models.TextField(blank=True)
    house_number = models.TextField(blank=True)
    box = models.TextField(blank=True)
    extra_address_info = models.TextField(blank=True)
    date_striking_off = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "adresse (BCE)"
        verbose_name_plural = "adresses (BCE)"

    def __str__(self) -> str:
        return f"{self.street_fr or self.street_nl} {self.house_number}"


class Activity(models.Model):
    entity_number = models.CharField(max_length=10, db_index=True)
    activity_group = models.CharField(max_length=10)
    nace_version = models.CharField(max_length=10)
    nace_code = models.CharField(max_length=20)
    classification = models.CharField(max_length=10)

    class Meta:
        verbose_name = "activité (BCE)"
        verbose_name_plural = "activités (BCE)"

    def __str__(self) -> str:
        return f"{self.nace_code} ({self.nace_version})"


class Contact(models.Model):
    entity_number = models.CharField(max_length=10, db_index=True)
    entity_contact = models.CharField(max_length=10)
    contact_type = models.CharField(max_length=10)
    value = models.TextField()

    class Meta:
        verbose_name = "coordonnée (BCE)"
        verbose_name_plural = "coordonnées (BCE)"

    def __str__(self) -> str:
        return self.value


class Code(models.Model):
    category = models.CharField(max_length=50)
    code = models.CharField(max_length=20)
    language = models.CharField(max_length=2)
    description = models.TextField()

    class Meta:
        verbose_name = "libellé de code (BCE)"
        verbose_name_plural = "libellés de codes (BCE)"
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["category", "code", "language"], name="bce_code_unique")
        ]

    def __str__(self) -> str:
        return f"{self.category} {self.code}"


class ImportRun(models.Model):
    class Kind(models.TextChoices):
        FULL = "full", "Export complet"
        UPDATE = "update", "Mise à jour"

    class Status(models.TextChoices):
        RUNNING = "running", "En cours"
        SUCCESS = "success", "Réussi"
        FAILED = "failed", "Échoué"

    kind = models.CharField("type", max_length=10, choices=Kind.choices)
    file_name = models.CharField("fichier", max_length=255)
    extract_number = models.PositiveIntegerField("numéro d'extraction", null=True, blank=True)
    snapshot_date = models.DateField("date des données", null=True, blank=True)
    started_at = models.DateTimeField("début", default=timezone.now)
    finished_at = models.DateTimeField("fin", null=True, blank=True)
    status = models.CharField(
        "statut", max_length=10, choices=Status.choices, default=Status.RUNNING
    )
    counts = models.JSONField("lignes traitées", default=dict, blank=True)
    changed_enterprises = models.PositiveIntegerField("entreprises modifiées", default=0)
    notes = models.TextField("remarques", blank=True)
    error = models.TextField("erreur", blank=True)

    class Meta:
        verbose_name = "import BCE"
        verbose_name_plural = "imports BCE"
        ordering: ClassVar = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} n° {self.extract_number} ({self.get_status_display()})"
