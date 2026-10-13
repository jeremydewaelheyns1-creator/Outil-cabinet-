"""Dossier actif : le client choisi en haut de l'écran.

Comme dans un logiciel comptable par dossier, on choisit un client une fois ; il reste
affiché en haut de l'écran. Dans un dossier, l'écran ne montre que lui (D-026) : un en-tête
fixe, en haut les onglets du travail fréquent (Clôture, Déclaration TVA, Versements
anticipés, Documents), à gauche un panneau « paperasse » comme FID-Manager (Fiche, Organisation,
Suivi, Conformité, Facturation), chaque page à un clic. Changer de client garde la rubrique
ouverte (on passe des « Mandataires » d'un client à ceux d'un autre).

Le dossier actif et les derniers dossiers ouverts sont gardés dans la session (identifiants
seulement) ; la visibilité est revérifiée à chaque lecture.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.http import HttpRequest

from apps.core.models import User

from .models import Client, Relation

SESSION_CURRENT = "dossier_actif"
SESSION_RECENT = "dossiers_recents"
RECENT_SIZE = 8


@dataclass(frozen=True)
class Section:
    """Une entrée du dossier : page existante (`url_name`) ou page à construire (`slug`)."""

    url_name: str
    label: str
    for_persons: bool = True
    for_entities: bool = True
    vat_only: bool = False  # seulement pour un client assujetti à la TVA
    slug: str = ""  # page « à construire » (url_name == WORK)
    count: str = ""  # compteur affiché à côté (clé de `counts`)

    @property
    def key(self) -> str:
        """Identifiant de la page affichée (nom d'URL, ou « work:<slug> »)."""
        return f"{WORK}:{self.slug}" if self.slug else self.url_name


@dataclass(frozen=True)
class Group:
    label: str
    sections: tuple[Section, ...]


WORK = "work"  # page « à construire » (onglets du haut, entrées prévues à gauche)
HISTORY = Section("history", "Historique")

# D-026 — En haut : le travail le plus fréquent. Contenu défini un par un avec Jeremy.
TOP: tuple[Section, ...] = (
    Section(WORK, "Clôture", slug="cloture"),
    Section(WORK, "Déclaration TVA", slug="tva", vat_only=True),
    Section(WORK, "Versements anticipés", slug="versements-anticipes"),
    Section(WORK, "Documents", slug="documents"),
)

# À gauche : la « paperasse », comme le panneau latéral de FID-Manager.
SIDE: tuple[Group, ...] = (
    Group(
        "Fiche",
        (
            Section("identity", "Identité et coordonnées"),
            Section("public_data", "BCE et TVA", for_persons=False),
            Section("moniteur", "Moniteur belge", for_persons=False),
            Section("annual_accounts", "Comptes annuels", for_persons=False),
            Section("team", "Équipe du cabinet"),
        ),
    ),
    Group(
        "Organisation",
        (
            Section("mandates", "Mandataires", count="mandates"),
            Section("shareholders", "Actionnaires", count="shareholders"),
            Section("ubo", "Bénéficiaires effectifs (UBO)", for_persons=False, count="ubo"),
            Section("other_relations", "Autres relations", count="others"),
        ),
    ),
    Group(
        "Suivi",
        (Section("tasks", "Échéances", count="overdue"), HISTORY),
    ),
    Group(
        "Conformité",
        (
            Section(WORK, "Anti-blanchiment", slug="anti-blanchiment"),
            Section(WORK, "Pièces d'identité", slug="pieces-identite"),
        ),
    ),
    Group(
        "Facturation",
        (
            Section(WORK, "Honoraires", slug="honoraires"),
            Section(WORK, "Factures", slug="factures"),
        ),
    ),
)

SECTIONS: tuple[Section, ...] = (*TOP, *(s for g in SIDE for s in g.sections))
SECTION_NAMES = {s.url_name for s in SECTIONS if s.url_name != WORK}
WORK_PAGES = {s.slug: s for s in SECTIONS if s.slug}


# Pages « Organisation » : quels rôles de relation chacune montre.
RELATION_PAGES: dict[str, tuple[str, ...]] = {
    "mandates": (*Relation.MANAGEMENT_ROLES, Relation.Role.PERMANENT_REPRESENTATIVE),
    "shareholders": (Relation.Role.SHAREHOLDER,),
    "other_relations": (
        Relation.Role.SPOUSE,
        Relation.Role.BENEFICIAL_OWNER,
        Relation.Role.OTHER,
    ),
}


def page_for_role(role: str) -> str:
    return next((page for page, roles in RELATION_PAGES.items() if role in roles), "mandates")


def _allowed(section: Section, client: Client) -> bool:
    if section.vat_only and client.vat_status != Client.VatStatus.SUBJECT:
        return False
    return section.for_persons if client.is_person else section.for_entities


def sections_for(client: Client) -> list[Section]:
    return [s for s in SECTIONS if _allowed(s, client)]


def top_for(client: Client) -> list[Section]:
    return [s for s in TOP if _allowed(s, client)]


def side_for(client: Client) -> list[Group]:
    groups = [Group(g.label, tuple(s for s in g.sections if _allowed(s, client))) for g in SIDE]
    return [g for g in groups if g.sections]


def activate(request: HttpRequest, client: Client) -> None:
    request.session[SESSION_CURRENT] = client.pk
    recent = [pk for pk in request.session.get(SESSION_RECENT, []) if pk != client.pk]
    request.session[SESSION_RECENT] = [client.pk, *recent][:RECENT_SIZE]
    request._dossier = client  # type: ignore[attr-defined]


def close(request: HttpRequest) -> None:
    request.session.pop(SESSION_CURRENT, None)
    request._dossier = None  # type: ignore[attr-defined]


def current(request: HttpRequest) -> Client | None:
    """Client actif, s'il est toujours visible par l'utilisateur."""
    if hasattr(request, "_dossier"):
        return request._dossier  # type: ignore[no-any-return]
    client = None
    pk = request.session.get(SESSION_CURRENT)
    if pk and isinstance(request.user, User):
        client = (
            Client.objects.visible_to(request.user)
            .select_related("portfolio")
            .filter(pk=pk)
            .first()
        )
    request._dossier = client  # type: ignore[attr-defined]
    return client


def recent(request: HttpRequest, exclude: Client | None = None) -> list[Client]:
    if not isinstance(request.user, User):
        return []
    ids = [pk for pk in request.session.get(SESSION_RECENT, []) if not exclude or pk != exclude.pk]
    found = {c.pk: c for c in Client.objects.visible_to(request.user).filter(pk__in=ids)}
    return [found[pk] for pk in ids if pk in found]


# Écrans d'action rattachés à une rubrique (pour la surligner dans le menu).
# Rubrique d'arrivée à l'ouverture d'un dossier (D-025 : plus de Synthèse).
DEFAULT_SECTION = "identity"

ACTION_SECTIONS = {
    "detail": DEFAULT_SECTION,  # ancienne adresse de la Synthèse : ouvre la Fiche
    "edit": "identity",
    "assignments": "team",
    "official_function_add": "public_data",
}


def section_of(request: HttpRequest) -> str:
    """Rubrique affichée, pour la garder en changeant de client."""
    match = request.resolver_match
    if match is None or match.namespace != "clients" or not match.url_name:
        return DEFAULT_SECTION
    if match.url_name in SECTION_NAMES:
        return match.url_name
    if match.url_name == WORK:
        return f"{WORK}:{match.kwargs.get('slug', '')}"
    if match.url_name == "relation_add":
        return page_for_role(str(request.GET.get("role", "")))
    if match.url_name == "relation_edit":
        role = (
            Relation.objects.filter(pk=match.kwargs.get("relation_pk", 0))
            .values_list("role", flat=True)
            .first()
        )
        return page_for_role(role or "")
    return ACTION_SECTIONS.get(match.url_name, DEFAULT_SECTION)


@dataclass(frozen=True)
class Link:
    """Une relation affichée sous le nom du client (cliquable vers l'autre dossier)."""

    other: Client
    role: str


def header_relations(client: Client, user: User, limit: int = 8) -> tuple[list[Link], int]:
    """Relations en cours du client, dans les deux sens, limitées aux fiches visibles."""
    from django.db.models import Q

    from .models import Relation

    visible = Client.objects.visible_to(user)
    relations = (
        Relation.objects.current()
        .filter(Q(entity=client, person__in=visible) | Q(person=client, entity__in=visible))
        .select_related("entity", "person")
    )
    links: list[Link] = []
    seen: dict[int, Link] = {}
    order = {r: i for i, r in enumerate(Relation.MANAGEMENT_ROLES)}
    for relation in sorted(relations, key=lambda r: order.get(r.role, 99)):
        other = relation.person if relation.entity_id == client.pk else relation.entity
        role = relation.get_role_display()
        if relation.person_id == client.pk and relation.role != Relation.Role.SPOUSE:
            role = f"{role} de"
        if other.pk in seen:
            continue
        seen[other.pk] = Link(other, role)
        links.append(seen[other.pk])
    return links[:limit], max(0, len(links) - limit)
