"""Calcul des bénéficiaires effectifs (UBO) à partir des relations encodées.

Le calcul propose, le collaborateur décide : rien n'est enregistré automatiquement. Le
résultat sert à préremplir la déclaration et à signaler les écarts avec les bénéficiaires
déjà déclarés (relation « bénéficiaire effectif déclaré »).

Règles appliquées (loi du 18 septembre 2017, art. 4, 27°) :
- société : toute personne physique qui détient, directement ou indirectement, plus de 25 %
  des actions ou des droits de vote (seuil et inclusion paramétrables, voir settings) ;
- détention indirecte : on additionne tous les chemins de détention. Pour le capital, les
  pourcentages sont multipliés le long du chemin. Pour les droits de vote, si la personne
  contrôle (plus de 50 % des votes) chaque société intermédiaire, elle dispose de toute la
  participation de la dernière intermédiaire ; sinon les pourcentages sont multipliés ;
- à défaut de détenteur au-dessus du seuil, les dirigeants principaux sont proposés ;
- ASBL et fondations : administrateurs, gestion journalière, représentants permanents.

C'est une estimation à vérifier : des chemins de détention qui se recoupent peuvent être
comptés deux fois, et une intermédiaire dont l'actionnariat n'est pas encodé est signalée.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from ..models import Client, Relation

HUNDRED = Decimal(100)
CONTROL_THRESHOLD = Decimal(50)
MAX_DEPTH = 10


class Basis:
    OWNERSHIP = "ownership"
    FALLBACK_MANAGEMENT = "fallback_management"
    NONPROFIT_MANAGEMENT = "nonprofit_management"


BASIS_LABELS = {
    Basis.OWNERSHIP: "Détention du capital ou des droits de vote",
    Basis.FALLBACK_MANAGEMENT: "Dirigeant principal (aucun détenteur au-dessus du seuil)",
    Basis.NONPROFIT_MANAGEMENT: "Administrateur ou gestion journalière (ASBL, fondation)",
}

MANAGEMENT_ROLES = (*Relation.MANAGEMENT_ROLES, Relation.Role.PERMANENT_REPRESENTATIVE)


@dataclass
class HiddenClient:
    """Fiche d'un portefeuille privé que l'utilisateur ne peut pas voir : comptée dans le
    calcul, mais affichée sans nom ni lien."""

    pk: int
    name: str = "Fiche d'un portefeuille privé"
    is_hidden: bool = True

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return ""


Party = Client | HiddenClient


@dataclass
class Holding:
    """Un chemin de détention, de la personne physique jusqu'à l'entité analysée."""

    chain: list[Party]
    share: Decimal | None
    voting: Decimal | None


@dataclass
class UboCandidate:
    person: Party
    basis: str
    share_percentage: Decimal = Decimal(0)
    voting_percentage: Decimal = Decimal(0)
    holdings: list[Holding] = field(default_factory=list)

    @property
    def basis_label(self) -> str:
        return BASIS_LABELS[self.basis]


@dataclass
class UboAnalysis:
    entity: Client
    candidates: list[UboCandidate]
    below_threshold: list[UboCandidate]
    declared: list[Party]
    unresolved_entities: list[Party]
    unknown_percentages: list[Relation]
    threshold: Decimal
    inclusive: bool

    def redact(self, visible_portfolio_ids: set[int]) -> UboAnalysis:
        """Masque les fiches que l'utilisateur ne peut pas voir (le calcul reste complet)."""

        def mask(party: Party) -> Party:
            if isinstance(party, Client) and party.portfolio_id not in visible_portfolio_ids:
                return HiddenClient(pk=party.pk)
            return party

        for candidate in [*self.candidates, *self.below_threshold]:
            candidate.person = mask(candidate.person)
            for holding in candidate.holdings:
                holding.chain = [mask(link) for link in holding.chain]
        self.declared = [mask(p) for p in self.declared]
        self.unresolved_entities = [mask(e) for e in self.unresolved_entities]
        return self

    @property
    def missing(self) -> list[Party]:
        """Bénéficiaires calculés mais non déclarés."""
        declared_ids = {p.pk for p in self.declared}
        return [c.person for c in self.candidates if c.person.pk not in declared_ids]

    @property
    def unexpected(self) -> list[Party]:
        """Bénéficiaires déclarés que le calcul ne retrouve pas."""
        computed_ids = {c.person.pk for c in self.candidates}
        return [p for p in self.declared if p.pk not in computed_ids]

    @property
    def is_complete(self) -> bool:
        return not self.unresolved_entities and not self.unknown_percentages

    @property
    def is_consistent(self) -> bool:
        return not self.missing and not self.unexpected

    @property
    def threshold_label(self) -> str:
        sign = "≥" if self.inclusive else ">"
        return f"{sign} {self.threshold.normalize():f} %"


def _above(value: Decimal, threshold: Decimal, inclusive: bool) -> bool:
    return value >= threshold if inclusive else value > threshold


def _voting(relation: Relation) -> Decimal | None:
    """À défaut de pourcentage de vote encodé, on suppose une voix par action."""
    if relation.voting_percentage is not None:
        return relation.voting_percentage
    return relation.share_percentage


class _Walker:
    def __init__(self, on: date) -> None:
        self.on = on
        self.unresolved: dict[int, Client] = {}
        self.unknown: list[Relation] = []

    def shareholders(self, entity: Client) -> list[Relation]:
        return list(
            Relation.objects.current(self.on)
            .filter(entity=entity, role=Relation.Role.SHAREHOLDER)
            .select_related("person", "entity")
        )

    def paths(
        self, entity: Client, visited: frozenset[int], depth: int
    ) -> Iterator[list[Relation]]:
        """Chemins [lien vers l'entité, ..., lien de la personne physique]."""
        for relation in self.shareholders(entity):
            holder = relation.person
            if holder.pk in visited:
                continue  # participation circulaire
            if relation.share_percentage is None and relation.voting_percentage is None:
                self.unknown.append(relation)
            if holder.is_person:
                yield [relation]
                continue
            if depth >= MAX_DEPTH:
                self.unresolved[holder.pk] = holder
                continue
            found = False
            for sub in self.paths(holder, visited | {holder.pk}, depth + 1):
                found = True
                yield [relation, *sub]
            if not found:
                self.unresolved[holder.pk] = holder


def _product(values: list[Decimal | None]) -> Decimal | None:
    """Pourcentage résultant d'une chaîne de pourcentages (None si l'un est inconnu)."""
    result = HUNDRED
    for value in values:
        if value is None:
            return None
        result = result * value / HUNDRED
    return result


def _measure(path: list[Relation]) -> Holding:
    votes = [_voting(r) for r in path]
    share = _product([r.share_percentage for r in path])
    voting = _product(votes)
    # Contrôle de toutes les intermédiaires : la personne dispose des votes du premier lien.
    first, upper = votes[0], votes[1:]
    if (
        voting is not None
        and first is not None
        and upper
        and all(v is not None and v > CONTROL_THRESHOLD for v in upper)
    ):
        voting = max(voting, first)
    chain: list[Party] = [path[-1].person, *(r.entity for r in reversed(path))]
    return Holding(chain=chain, share=share, voting=voting)


def _management(entity: Client, on: date, basis: str) -> list[UboCandidate]:
    relations = (
        Relation.objects.current(on)
        .filter(entity=entity, role__in=MANAGEMENT_ROLES, person__kind=Client.Kind.PERSON)
        .select_related("person")
        .order_by("person__name", "person__first_name")
    )
    seen: dict[int, UboCandidate] = {}
    for relation in relations:
        seen.setdefault(relation.person.pk, UboCandidate(person=relation.person, basis=basis))
    return list(seen.values())


def analyse(entity: Client, on: date | None = None) -> UboAnalysis:
    on = on or timezone.localdate()
    threshold: Decimal = settings.UBO_THRESHOLD_PERCENT
    inclusive: bool = settings.UBO_THRESHOLD_INCLUSIVE
    declared: list[Party] = [
        r.person
        for r in Relation.objects.current(on)
        .filter(entity=entity, role=Relation.Role.BENEFICIAL_OWNER)
        .select_related("person")
    ]
    walker = _Walker(on)
    candidates: list[UboCandidate] = []
    below: list[UboCandidate] = []

    if entity.kind == Client.Kind.NONPROFIT:
        candidates = _management(entity, on, Basis.NONPROFIT_MANAGEMENT)
    elif entity.kind != Client.Kind.PERSON:
        by_person: dict[int, UboCandidate] = {}
        for path in walker.paths(entity, frozenset({entity.pk}), 1):
            holding = _measure(path)
            person = holding.chain[0]
            candidate = by_person.setdefault(
                person.pk, UboCandidate(person=person, basis=Basis.OWNERSHIP)
            )
            candidate.holdings.append(holding)
            candidate.share_percentage += holding.share or Decimal(0)
            candidate.voting_percentage += holding.voting or Decimal(0)
        for candidate in sorted(
            by_person.values(),
            key=lambda c: (-max(c.share_percentage, c.voting_percentage), c.person.name),
        ):
            if _above(candidate.share_percentage, threshold, inclusive) or _above(
                candidate.voting_percentage, threshold, inclusive
            ):
                candidates.append(candidate)
            else:
                below.append(candidate)
        if not candidates:
            candidates = _management(entity, on, Basis.FALLBACK_MANAGEMENT)

    return UboAnalysis(
        entity=entity,
        candidates=candidates,
        below_threshold=below,
        declared=declared,
        unresolved_entities=list(walker.unresolved.values()),
        unknown_percentages=walker.unknown,
        threshold=threshold,
        inclusive=inclusive,
    )
