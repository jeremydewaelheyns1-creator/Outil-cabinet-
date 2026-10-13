"""Exploitation de la copie BCE : recherche, fiche publique, comparaison avec nos clients.

Principe : les champs « publics » (statut BCE, situation juridique, activités, date de début)
sont tenus à jour automatiquement. Les champs que le cabinet saisit lui-même (nom, forme
juridique, adresse) ne sont jamais écrasés : les différences sont proposées au collaborateur,
qui choisit de les appliquer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from django.utils import timezone

from apps.clients.models import Client, ContactPoint, field_label
from apps.core import events
from apps.core.models import User
from apps.core.text import normalize_key, normalize_text

from .models import Activity, Address, Code, Contact, Denomination, Enterprise, ImportRun

FRENCH = "1"
NORMAL_SITUATION = "000"
ACTIVE_STATUS = "AC"
REGISTERED_OFFICE = "REGO"

# Abréviations usuelles, à partir du libellé officiel de la forme juridique.
LEGAL_FORM_ABBREVIATIONS = {
    normalize_key(label): abbreviation
    for label, abbreviation in [
        ("Société à responsabilité limitée", "SRL"),
        ("Société privée à responsabilité limitée", "SPRL"),
        ("Société anonyme", "SA"),
        ("Société coopérative", "SC"),
        ("Société coopérative à responsabilité limitée", "SCRL"),
        ("Société coopérative à responsabilité illimitée", "SCRI"),
        ("Société en nom collectif", "SNC"),
        ("Société en commandite", "SComm"),
        ("Société en commandite simple", "SCS"),
        ("Société en commandite par actions", "SCA"),
        ("Association sans but lucratif", "ASBL"),
        ("Association internationale sans but lucratif", "AISBL"),
        ("Fondation d'utilité publique", "FUP"),
        ("Fondation privée", "Fondation privée"),
        ("Société européenne", "SE"),
        ("Groupement d'intérêt économique", "GIE"),
        ("Groupement européen d'intérêt économique", "GEIE"),
        ("Société simple", "Société simple"),
    ]
}
NONPROFIT_FORMS = {"ASBL", "AISBL", "FUP", "Fondation privée"}

COUNTRY_CODES = {
    normalize_key(name): code
    for name, code in [
        ("Belgique", "BE"),
        ("France", "FR"),
        ("Pays-Bas", "NL"),
        ("Luxembourg", "LU"),
        ("Allemagne", "DE"),
        ("Espagne", "ES"),
        ("Italie", "IT"),
        ("Royaume-Uni", "GB"),
        ("Suisse", "CH"),
    ]
}

CONTACT_KINDS = {
    "EMAIL": ContactPoint.Kind.EMAIL,
    "TEL": ContactPoint.Kind.PHONE,
    "WEB": ContactPoint.Kind.WEBSITE,
}


# --- Libellés de codes ----------------------------------------------------------------------


def code_label(category: str, code: str) -> str:
    if not code:
        return ""
    labels = dict(
        Code.objects.filter(category=category, code=code).values_list("language", "description")
    )
    return labels.get("FR") or labels.get("NL") or code


def legal_form_abbreviation(label: str) -> str:
    return LEGAL_FORM_ABBREVIATIONS.get(normalize_key(label), label[:100])


# --- Fiche publique -------------------------------------------------------------------------


@dataclass
class BceAddress:
    street: str
    house_number: str
    box: str
    postal_code: str
    city: str
    country: str | None

    @property
    def lines(self) -> list[str]:
        line1 = " ".join(p for p in [self.street, self.house_number] if p)
        if self.box:
            line1 = f"{line1} bte {self.box}"
        return [line for line in [line1, f"{self.postal_code} {self.city}".strip()] if line]


@dataclass
class BceActivity:
    code: str
    version: str
    label: str

    def as_json(self) -> dict[str, str]:
        return {"code": self.code, "version": self.version, "label": self.label}


@dataclass
class BceRecord:
    number: str
    type_of_enterprise: str
    name: str
    abbreviation: str
    commercial_names: list[str]
    legal_form: str
    legal_form_label: str
    status: str
    juridical_situation: str
    juridical_situation_label: str
    start_date: date | None
    address: BceAddress | None
    activities: list[BceActivity] = field(default_factory=list)
    contacts: list[tuple[str, str]] = field(default_factory=list)

    @property
    def is_person(self) -> bool:
        return self.type_of_enterprise == Enterprise.Type.PERSON

    @property
    def is_active(self) -> bool:
        return self.status == ACTIVE_STATUS

    @property
    def is_normal_situation(self) -> bool:
        return self.juridical_situation in ("", NORMAL_SITUATION)

    @property
    def client_kind(self) -> str:
        if self.is_person:
            return Client.Kind.PERSON
        if self.legal_form in NONPROFIT_FORMS:
            return Client.Kind.NONPROFIT
        return Client.Kind.COMPANY


def _pick_name(denominations: list[Denomination], kind: str) -> str:
    candidates = [d for d in denominations if d.type == kind]
    candidates.sort(key=lambda d: (d.language != FRENCH, d.name))
    return candidates[0].name if candidates else ""


def _registered_address(number: str) -> BceAddress | None:
    addresses = Address.objects.filter(entity_number=number, date_striking_off__isnull=True)
    address = addresses.filter(type_of_address=REGISTERED_OFFICE).first() or addresses.first()
    if address is None:
        return None
    country_name = address.country_fr or address.country_nl
    country = COUNTRY_CODES.get(normalize_key(country_name)) if country_name else "BE"
    return BceAddress(
        street=address.street_fr or address.street_nl,
        house_number=address.house_number,
        box=address.box,
        postal_code=address.zipcode,
        city=address.municipality_fr or address.municipality_nl,
        country=country,
    )


def _main_activities(number: str) -> list[BceActivity]:
    rows = list(
        Activity.objects.filter(entity_number=number, classification="MAIN").values_list(
            "nace_version", "nace_code"
        )
    )
    if not rows:
        return []
    latest = max(version for version, _ in rows)
    codes = sorted({code for version, code in rows if version == latest})
    return [BceActivity(code, latest, code_label(f"Nace{latest}", code)) for code in codes]


def lookup(number: str) -> BceRecord | None:
    """Fiche publique d'une entreprise, ou None si elle n'est pas (ou plus) dans la BCE."""
    enterprise = Enterprise.objects.filter(number=number).first()
    if enterprise is None:
        return None
    denominations = list(Denomination.objects.filter(entity_number=number))
    form_label = code_label("JuridicalForm", enterprise.juridical_form)
    return BceRecord(
        number=number,
        type_of_enterprise=enterprise.type_of_enterprise,
        name=_pick_name(denominations, Denomination.Type.LEGAL),
        abbreviation=_pick_name(denominations, Denomination.Type.ABBREVIATION),
        commercial_names=sorted(
            {d.name for d in denominations if d.type == Denomination.Type.COMMERCIAL}
        ),
        legal_form=legal_form_abbreviation(form_label) if enterprise.juridical_form else "",
        legal_form_label=form_label if enterprise.juridical_form else "",
        status=enterprise.status,
        juridical_situation=enterprise.juridical_situation,
        juridical_situation_label=code_label("JuridicalSituation", enterprise.juridical_situation),
        start_date=enterprise.start_date,
        address=_registered_address(number),
        activities=_main_activities(number),
        contacts=sorted(
            set(
                Contact.objects.filter(entity_number=number, entity_contact="ENT").values_list(
                    "contact_type", "value"
                )
            )
        ),
    )


def has_data() -> bool:
    return ImportRun.objects.filter(status=ImportRun.Status.SUCCESS).exists()


# --- Recherche ------------------------------------------------------------------------------


@dataclass
class SearchHit:
    number: str
    name: str
    city: str
    client_id: int | None


def search(text: str, limit: int = 15) -> list[SearchHit]:
    text = text.strip()
    digits = "".join(c for c in text if c.isdigit())
    numbers: list[str]
    if len(digits) >= 4 and len(digits) >= len(text.replace(".", "").replace(" ", "")) - 2:
        if len(digits) == 9:
            digits = f"0{digits}"
        numbers = list(
            Enterprise.objects.filter(number__startswith=digits)
            .order_by("number")
            .values_list("number", flat=True)[:limit]
        )
    else:
        needle = normalize_text(text)
        if len(needle) < 3:
            return []
        numbers = list(
            Denomination.objects.filter(search_name__contains=needle)
            .order_by("entity_number")
            .values_list("entity_number", flat=True)
            .distinct()[:limit]
        )
    names: dict[str, str] = {}
    for d in Denomination.objects.filter(
        entity_number__in=numbers, type=Denomination.Type.LEGAL
    ).order_by("language"):
        names.setdefault(d.entity_number, d.name)
    cities: dict[str, str] = {}
    for a in Address.objects.filter(entity_number__in=numbers, type_of_address=REGISTERED_OFFICE):
        cities.setdefault(a.entity_number, a.municipality_fr or a.municipality_nl)
    clients = dict(
        Client.objects.filter(enterprise_number__in=numbers).values_list("enterprise_number", "pk")
    )
    return [SearchHit(n, names.get(n, ""), cities.get(n, ""), clients.get(n)) for n in numbers]


# --- Comparaison et mise à jour des clients -------------------------------------------------


@dataclass
class Difference:
    field: str
    label: str
    current: str
    proposed: str


EDITABLE_FIELDS = ("name", "legal_form", "street", "house_number", "box", "postal_code", "city")


def proposed_values(record: BceRecord) -> dict[str, Any]:
    """Valeurs que la BCE suggère pour les champs saisis par le cabinet."""
    values: dict[str, Any] = {}
    if not record.is_person and record.name:
        values["name"] = record.name
        values["legal_form"] = record.legal_form
    if record.address:
        values.update(
            street=record.address.street,
            house_number=record.address.house_number,
            box=record.address.box,
            postal_code=record.address.postal_code,
            city=record.address.city,
        )
        if record.address.country:
            values["country"] = record.address.country
    return values


def public_values(record: BceRecord | None) -> dict[str, Any]:
    """Champs « BCE » du client, toujours alignés sur la copie publique."""
    if record is None:
        return {
            "bce_status": "absent",
            "bce_juridical_situation": "",
            "nace_codes": [],
        }
    return {
        "founded_on": record.start_date,
        "bce_status": record.status,
        "bce_juridical_situation": (
            "" if record.is_normal_situation else record.juridical_situation_label
        ),
        "nace_codes": [a.as_json() for a in record.activities],
    }


def differences(client: Client, record: BceRecord) -> list[Difference]:
    result = []
    for name, value in proposed_values(record).items():
        if name not in EDITABLE_FIELDS:
            continue
        current = str(getattr(client, name) or "")
        if normalize_text(current) != normalize_text(str(value or "")):
            label = field_label(name)
            result.append(Difference(name, label, current, str(value or "")))
    return result


def sync_public_fields(client: Client, record: BceRecord | None) -> list[str]:
    changed = []
    for name, value in public_values(record).items():
        if getattr(client, name) != value:
            setattr(client, name, value)
            changed.append(name)
    client.bce_synced_at = timezone.now()
    client.save()
    return changed


def _sync_contacts(client: Client, record: BceRecord) -> None:
    for contact_type, value in record.contacts:
        kind = CONTACT_KINDS.get(contact_type)
        if kind is None or not value:
            continue
        ContactPoint.objects.get_or_create(
            client=client, kind=kind, value=value[:254], defaults={"source": "bce"}
        )


def fill_blanks(client: Client) -> BceRecord | None:
    """Complète une fiche client avec la BCE sans écraser ce qui a déjà été saisi."""
    if not client.enterprise_number:
        return None
    record = lookup(client.enterprise_number)
    if record is None:
        if has_data():
            sync_public_fields(client, None)
        return None
    for name, value in proposed_values(record).items():
        if value and not getattr(client, name):
            setattr(client, name, value)
    sync_public_fields(client, record)
    _sync_contacts(client, record)
    return record


def apply_differences(client: Client, fields: list[str], actor: User | None) -> list[str]:
    """Applique les valeurs BCE choisies par le collaborateur."""
    if not client.enterprise_number:
        return []
    record = lookup(client.enterprise_number)
    if record is None:
        return []
    values = proposed_values(record)
    applied = [f for f in fields if f in EDITABLE_FIELDS and f in values]
    for name in applied:
        setattr(client, name, values[name] or "")
    if applied:
        client.save()
        events.emit(
            "client.updated_from_bce", subject=client, actor=actor, payload={"fields": applied}
        )
    return applied


def notify_changed_clients(run: ImportRun, numbers: set[str]) -> int:
    """Après une mise à jour BCE : un événement par client dont l'entreprise a changé."""
    if not numbers:
        return 0
    count = 0
    clients = Client.objects.filter(enterprise_number__in=numbers).only("pk")
    for client in clients.iterator():
        events.emit(
            "bce.enterprise_changed",
            subject=client,
            payload={"import_run": run.pk, "extract_number": run.extract_number},
            idempotency_key=f"bce-change-{run.pk}-{client.pk}",
        )
        count += 1
    return count
