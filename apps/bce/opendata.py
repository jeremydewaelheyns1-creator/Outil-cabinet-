"""Lecture et import des archives « KBO Open Data » de la BCE.

Deux types d'archives (fichiers ZIP de CSV, encodés en UTF-8) :
- export complet : `enterprise.csv`, `denomination.csv`, ... ; on vide puis recharge ;
- mise à jour : `enterprise_delete.csv` + `enterprise_insert.csv`, ... ; pour chaque table,
  on supprime toutes les lignes des numéros listés dans `_delete`, puis on insère `_insert`.

Le chargement utilise COPY (PostgreSQL) en flux : quelques minutes pour plusieurs millions de
lignes, sans charger les fichiers en mémoire. Chaque import est une seule transaction : en cas
d'erreur, la copie précédente reste intacte.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from django.db import connection, models, transaction
from django.utils import timezone

from apps.core.text import normalize_text

from .models import Activity, Address, Code, Contact, Denomination, Enterprise, ImportRun

logger = logging.getLogger(__name__)

Row = dict[str, str]
DbRow = tuple[Any, ...]

ENTERPRISE_NUMBER = re.compile(r"^\d{4}\.\d{3}\.\d{3}$")
CODE_LANGUAGES = {"FR", "NL"}
DELETE_CHUNK = 5000


class OpenDataError(Exception):
    """Archive invalide ou incohérente : l'import est refusé."""


def enterprise_number(value: str) -> str | None:
    """'0403.170.701' → '0403170701'. Les unités d'établissement (2.xxx...) sont ignorées."""
    value = (value or "").strip()
    if ENTERPRISE_NUMBER.match(value):
        return value.replace(".", "")
    return None


def parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%d-%m-%Y").date()


# --- Description des tables -----------------------------------------------------------------


@dataclass(frozen=True)
class Table:
    csv_name: str
    model: type[models.Model]
    columns: tuple[str, ...]
    key_column: str
    transform: Callable[[Row], DbRow | None]


def _enterprise(row: Row) -> DbRow | None:
    number = enterprise_number(row["EnterpriseNumber"])
    if number is None:
        return None
    return (
        number,
        row["Status"],
        row["JuridicalSituation"],
        row["TypeOfEnterprise"],
        row.get("JuridicalForm", ""),
        row.get("JuridicalFormCAC", ""),
        parse_date(row.get("StartDate", "")),
    )


def _denomination(row: Row) -> DbRow | None:
    number = enterprise_number(row["EntityNumber"])
    if number is None:
        return None
    name = row["Denomination"].strip()
    return (number, row["Language"], row["TypeOfDenomination"], name, normalize_text(name))


def _address(row: Row) -> DbRow | None:
    number = enterprise_number(row["EntityNumber"])
    if number is None:
        return None
    return (
        number,
        row["TypeOfAddress"],
        row.get("CountryNL", ""),
        row.get("CountryFR", ""),
        row.get("Zipcode", ""),
        row.get("MunicipalityNL", ""),
        row.get("MunicipalityFR", ""),
        row.get("StreetNL", ""),
        row.get("StreetFR", ""),
        row.get("HouseNumber", ""),
        row.get("Box", ""),
        row.get("ExtraAddressInfo", ""),
        parse_date(row.get("DateStrikingOff", "")),
    )


def _activity(row: Row) -> DbRow | None:
    number = enterprise_number(row["EntityNumber"])
    if number is None or row.get("Classification") != "MAIN":
        return None
    return (
        number,
        row["ActivityGroup"],
        row["NaceVersion"],
        row["NaceCode"],
        row["Classification"],
    )


def _contact(row: Row) -> DbRow | None:
    number = enterprise_number(row["EntityNumber"])
    if number is None:
        return None
    return (number, row["EntityContact"], row["ContactType"], row["Value"].strip())


def _code(row: Row) -> DbRow | None:
    if row["Language"] not in CODE_LANGUAGES:
        return None
    return (row["Category"], row["Code"], row["Language"], row["Description"])


TABLES: tuple[Table, ...] = (
    Table(
        "enterprise",
        Enterprise,
        (
            "number",
            "status",
            "juridical_situation",
            "type_of_enterprise",
            "juridical_form",
            "juridical_form_cac",
            "start_date",
        ),
        "number",
        _enterprise,
    ),
    Table(
        "denomination",
        Denomination,
        ("entity_number", "language", "type", "name", "search_name"),
        "entity_number",
        _denomination,
    ),
    Table(
        "address",
        Address,
        (
            "entity_number",
            "type_of_address",
            "country_nl",
            "country_fr",
            "zipcode",
            "municipality_nl",
            "municipality_fr",
            "street_nl",
            "street_fr",
            "house_number",
            "box",
            "extra_address_info",
            "date_striking_off",
        ),
        "entity_number",
        _address,
    ),
    Table(
        "activity",
        Activity,
        ("entity_number", "activity_group", "nace_version", "nace_code", "classification"),
        "entity_number",
        _activity,
    ),
    Table(
        "contact",
        Contact,
        ("entity_number", "entity_contact", "contact_type", "value"),
        "entity_number",
        _contact,
    ),
)

CODE_TABLE = Table("code", Code, ("category", "code", "language", "description"), "category", _code)


# --- Lecture de l'archive -------------------------------------------------------------------


class Archive:
    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self.zip = zipfile.ZipFile(path)
        except zipfile.BadZipFile as exc:
            raise OpenDataError(f"{path.name} n'est pas une archive ZIP valide.") from exc
        self.names = {Path(n).name.lower(): n for n in self.zip.namelist()}
        self.meta = self._read_meta()

    def __enter__(self) -> Archive:
        return self

    def __exit__(self, *exc: object) -> None:
        self.zip.close()

    def has(self, csv_name: str) -> bool:
        return f"{csv_name}.csv" in self.names

    def rows(self, csv_name: str) -> Iterator[Row]:
        member = self.names.get(f"{csv_name}.csv")
        if member is None:
            raise OpenDataError(f"Fichier {csv_name}.csv absent de l'archive.")
        with self.zip.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            yield from csv.DictReader(text)

    def _read_meta(self) -> dict[str, str]:
        if not self.has("meta"):
            raise OpenDataError("Fichier meta.csv absent : ce n'est pas une archive BCE.")
        return {row["Variable"]: row["Value"] for row in self.rows("meta")}

    @property
    def kind(self) -> str:
        extract_type = self.meta.get("ExtractType", "").lower()
        if extract_type not in {ImportRun.Kind.FULL, ImportRun.Kind.UPDATE}:
            raise OpenDataError(f"Type d'extraction inconnu : {extract_type!r}.")
        return extract_type

    @property
    def extract_number(self) -> int | None:
        value = self.meta.get("ExtractNumber", "").strip()
        return int(value) if value.isdigit() else None

    @property
    def snapshot_date(self) -> date | None:
        return parse_date(self.meta.get("SnapshotDate", ""))


# --- Écriture en base -----------------------------------------------------------------------


def _table_name(model: type[models.Model]) -> str:
    return connection.ops.quote_name(model._meta.db_table)


def _copy(table: Table, rows: Iterable[Row]) -> int:
    columns = ", ".join(connection.ops.quote_name(c) for c in table.columns)
    count = 0
    with (
        connection.cursor() as cursor,
        cursor.copy(f"COPY {_table_name(table.model)} ({columns}) FROM STDIN") as copy,
    ):
        for row in rows:
            values = table.transform(row)
            if values is None:
                continue
            copy.write_row(values)
            count += 1
            if count % 500_000 == 0:
                logger.info("BCE %s : %s lignes chargées", table.csv_name, count)
    return count


def _truncate(model: type[models.Model]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE {_table_name(model)}")


def _delete_keys(table: Table, keys: set[str]) -> None:
    ordered = sorted(keys)
    for start in range(0, len(ordered), DELETE_CHUNK):
        chunk = ordered[start : start + DELETE_CHUNK]
        table.model._default_manager.filter(**{f"{table.key_column}__in": chunk})._raw_delete(
            connection.alias
        )


def _keys_from_delete_file(archive: Archive, csv_name: str) -> set[str]:
    """Le fichier `_delete` ne contient qu'une colonne : le numéro concerné."""
    keys: set[str] = set()
    for row in archive.rows(f"{csv_name}_delete"):
        value = next(iter(row.values()), "")
        number = enterprise_number(value)
        if number:
            keys.add(number)
    return keys


def _last_success() -> ImportRun | None:
    return (
        ImportRun.objects.filter(status=ImportRun.Status.SUCCESS, extract_number__isnull=False)
        .order_by("-extract_number")
        .first()
    )


def _check_sequence(archive: Archive) -> str:
    """Refuse une archive déjà appliquée ou une mise à jour sans export complet préalable."""
    last = _last_success()
    number = archive.extract_number
    if archive.kind == ImportRun.Kind.UPDATE:
        if last is None:
            raise OpenDataError("Importez d'abord un export complet avant une mise à jour.")
        if number is not None and last.extract_number is not None:
            if number <= last.extract_number:
                raise OpenDataError(
                    f"Mise à jour n° {number} déjà appliquée (dernier import : "
                    f"n° {last.extract_number})."
                )
            if number > last.extract_number + 1:
                return (
                    f"Mises à jour manquantes entre le n° {last.extract_number} et le "
                    f"n° {number} : importez-les ou importez le prochain export complet."
                )
    return ""


def import_archive(path: Path) -> ImportRun:
    """Importe une archive complète ou de mise à jour. Retourne le suivi de l'import."""
    with Archive(path) as archive:
        kind = archive.kind
        notes = _check_sequence(archive)
        run = ImportRun.objects.create(
            kind=kind,
            file_name=path.name[:255],
            extract_number=archive.extract_number,
            snapshot_date=archive.snapshot_date,
            notes=notes,
        )
        try:
            with transaction.atomic():
                if kind == ImportRun.Kind.FULL:
                    counts, changed = _import_full(archive), set[str]()
                else:
                    counts, changed = _import_update(archive)
        except Exception as exc:
            run.status = ImportRun.Status.FAILED
            run.error = f"{type(exc).__name__}: {exc}"[:4000]
            run.finished_at = timezone.now()
            run.save()
            raise
        run.status = ImportRun.Status.SUCCESS
        run.counts = counts
        run.changed_enterprises = len(changed)
        run.finished_at = timezone.now()
        run.save()

    from .services import notify_changed_clients

    notify_changed_clients(run, changed)
    return run


def _import_full(archive: Archive) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in (*TABLES, CODE_TABLE):
        if not archive.has(table.csv_name):
            raise OpenDataError(f"Fichier {table.csv_name}.csv absent de l'export complet.")
        _truncate(table.model)
        counts[table.csv_name] = _copy(table, archive.rows(table.csv_name))
        logger.info("BCE %s : %s lignes", table.csv_name, counts[table.csv_name])
    return counts


def _import_update(archive: Archive) -> tuple[dict[str, int], set[str]]:
    counts: dict[str, int] = {}
    changed: set[str] = set()
    for table in TABLES:
        if archive.has(f"{table.csv_name}_delete"):
            keys = _keys_from_delete_file(archive, table.csv_name)
            _delete_keys(table, keys)
            changed |= keys
            counts[f"{table.csv_name}_delete"] = len(keys)
        if archive.has(f"{table.csv_name}_insert"):
            inserted: set[str] = set()

            def tracked(rows: Iterator[Row], seen: set[str] = inserted) -> Iterator[Row]:
                for row in rows:
                    number = enterprise_number(next(iter(row.values()), ""))
                    if number:
                        seen.add(number)
                    yield row

            counts[f"{table.csv_name}_insert"] = _copy(
                table, tracked(archive.rows(f"{table.csv_name}_insert"))
            )
            changed |= inserted
    if archive.has("code"):
        _truncate(Code)
        counts["code"] = _copy(CODE_TABLE, archive.rows("code"))
    return counts, changed
