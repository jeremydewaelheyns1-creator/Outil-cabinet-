"""Quel dossier pour cet e-mail ? (D-060) — sans IA, avec des règles simples et vérifiables.

Dans l'ordre :
1. une référence de nos demandes dans l'objet (« [réf. AB12CD] ») → le dossier de la demande ;
2. l'adresse e-mail est dans une fiche :
   - fiche d'une société → **ce dossier** (classé dans la société) ;
   - fiche d'une personne liée à une ou plusieurs sociétés (gérant, actionnaire…) → c'est son
     **adresse privée** : l'employé choisit « société » ou « personne physique » (sous-dossier
     de la société) ;
   - personne cliente sans société → son propre dossier ;
3. un numéro d'entreprise connu dans l'objet ou le texte (courriers du SPF…) → ce dossier ;
4. sinon : pas de suggestion, l'employé choisit lui-même.
Seuls les dossiers que l'employé peut voir sont proposés.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db.models import QuerySet

from apps.clients.identifiers import normalize_enterprise_number
from apps.clients.models import Client, ContactPoint, Relation
from apps.core.models import User

REFERENCE = re.compile(r"\[réf\. ([A-Z0-9]{4,20})\]")
ENTERPRISE = re.compile(r"\b(?:BE\s?)?([01]\d{3})[.\s]?(\d{3})[.\s]?(\d{3})\b")


@dataclass(frozen=True)
class Suggestion:
    client: Client | None = None
    person: Client | None = None
    choice_needed: bool = False
    reason: str = ""


def _visible(user: User) -> QuerySet[Client]:
    return Client.objects.visible_to(user)


def companies_of(person: Client, user: User) -> list[Client]:
    """Sociétés (en cours) auxquelles la personne est liée, parmi les dossiers visibles."""
    ids = Relation.objects.current().filter(person=person).values_list("entity_id", flat=True)
    return list(_visible(user).filter(pk__in=ids).exclude(kind=Client.Kind.PERSON).order_by("name"))


def by_address(address: str, user: User) -> Suggestion:
    if not address:
        return Suggestion()
    contacts = ContactPoint.objects.filter(
        kind=ContactPoint.Kind.EMAIL, value__iexact=address.strip(), client__in=_visible(user)
    ).select_related("client")
    owners = list(dict.fromkeys(c.client for c in contacts))
    companies = [c for c in owners if c.kind != Client.Kind.PERSON]
    if companies:
        return Suggestion(companies[0], reason="adresse de la société")
    for person in owners:
        linked = companies_of(person, user)
        if linked:
            return Suggestion(
                linked[0], person, choice_needed=True,
                reason=f"adresse privée de {person.display_name}",
            )  # fmt: skip
        return Suggestion(person, reason="adresse de la personne")
    return Suggestion()


def by_reference(subject: str, user: User) -> Suggestion:
    from apps.documents.models import DocumentRequest

    found = REFERENCE.search(subject or "")
    if not found:
        return Suggestion()
    request = (
        DocumentRequest.objects.filter(reference=found.group(1), client__in=_visible(user))
        .select_related("client")
        .first()
    )
    return Suggestion(request.client, reason="réponse à une demande") if request else Suggestion()


def by_enterprise_number(text: str, user: User) -> Suggestion:
    numbers: list[str] = []
    for match in ENTERPRISE.finditer(text or ""):
        try:
            number = normalize_enterprise_number("".join(match.groups()))
        except ValidationError:
            continue
        if number and number not in numbers:
            numbers.append(number)
    if not numbers:
        return Suggestion()
    found = list(_visible(user).filter(enterprise_number__in=numbers[:20])[:2])
    if len(found) == 1:
        return Suggestion(found[0], reason="numéro d'entreprise dans l'e-mail")
    return Suggestion()


def suggest(*, addresses: list[str], subject: str, body: str, user: User) -> Suggestion:
    found = by_reference(subject, user)
    if found.client:
        return found
    for address in addresses:
        found = by_address(address, user)
        if found.client:
            return found
    return by_enterprise_number(f"{subject}\n{body[:20000]}", user)


@dataclass(frozen=True)
class Choice:
    value: str  # « c:<id> » ou « p:<société>:<personne> »
    label: str
    client: Client
    person: Client | None = None


def choices_for(person: Client, user: User) -> list[Choice]:
    """Adresse privée d'un dirigeant : chaque société, et sa personne physique sous chacune."""
    result: list[Choice] = []
    for company in companies_of(person, user):
        result.append(Choice(f"c:{company.pk}", f"{company.display_name} (société)", company))
        result.append(Choice(
            f"p:{company.pk}:{person.pk}",
            f"{person.display_name} (personne physique, dans {company.display_name})",
            company, person,
        ))  # fmt: skip
    return result


def resolve(value: str, user: User) -> tuple[Client, Client | None]:
    """Valeur choisie (« c:12 » ou « p:12:34 ») → (dossier, personne) visibles, sinon erreur."""
    parts = value.split(":")
    try:
        ids = [int(p) for p in parts[1:]]
    except ValueError as exc:
        raise ValueError("Choix invalide.") from exc
    visible = _visible(user)
    if parts[0] == "c" and len(ids) == 1:
        return visible.get(pk=ids[0]), None
    if parts[0] == "p" and len(ids) == 2:
        company, person = visible.get(pk=ids[0]), visible.get(pk=ids[1])
        if not Relation.objects.current().filter(entity=company, person=person).exists():
            raise ValueError("Cette personne n'est pas liée à ce dossier.")
        return company, person
    raise ValueError("Choix invalide.")
