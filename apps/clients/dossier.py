"""Dossier actif : le client choisi en haut de l'écran.

Comme dans un logiciel comptable par dossier, on choisit un client une fois ; il reste
affiché en haut de l'écran. Dans un dossier, l'écran ne montre que lui : un en-tête fixe, des
onglets (Fiche, Travail, Documents et conformité, Facturation) et leurs
sous-onglets ; un onglet « Accueil » ramène aux écrans du cabinet. Changer de client garde
la rubrique ouverte (on passe des « Relations » d'un client à celles d'un autre).

Le dossier actif et les derniers dossiers ouverts sont gardés dans la session (identifiants
seulement) ; la visibilité est revérifiée à chaque lecture.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.http import HttpRequest

from apps.core.models import User

from .models import Client

SESSION_CURRENT = "dossier_actif"
SESSION_RECENT = "dossiers_recents"
RECENT_SIZE = 8


@dataclass(frozen=True)
class Section:
    url_name: str
    label: str
    for_persons: bool = True
    for_entities: bool = True


# Organisation du dossier : quelques grands onglets stables, des sous-onglets dedans. Chaque
# nouvelle fonction vient se ranger dans l'onglet qui lui correspond (pas de nouvel onglet).
HISTORY = Section("history", "Historique")


@dataclass(frozen=True)
class Tab:
    key: str
    label: str
    sections: tuple[Section, ...] = ()
    upcoming: tuple[str, ...] = ()  # sous-onglets prévus, affichés grisés


TABS: tuple[Tab, ...] = (
    Tab(
        "fiche",
        "Fiche",
        (
            Section("identity", "Identité et coordonnées"),
            Section("relations", "Relations"),
            Section("ubo", "Bénéficiaires effectifs", for_persons=False),
            Section("public_data", "BCE et TVA", for_persons=False),
            Section("moniteur", "Moniteur belge", for_persons=False),
            Section("annual_accounts", "Comptes annuels", for_persons=False),
            Section("team", "Équipe du cabinet"),
        ),
    ),
    Tab("travail", "Travail", (Section("tasks", "Échéances"),), ("Prestations",)),
    Tab(
        "documents",
        "Documents et conformité",
        (),
        (
            "Pièces",
            "Courriers et e-mails",
            "Signatures",
            "Anti-blanchiment",
            "Pièces d'identité",
            "Déclarations UBO",
        ),
    ),
    Tab("facturation", "Facturation", (), ("Honoraires", "Factures")),
)

SECTIONS: tuple[Section, ...] = (*(s for t in TABS for s in t.sections), HISTORY)
SECTION_NAMES = {s.url_name for s in SECTIONS}
TAB_OF = {s.url_name: t.key for t in TABS for s in t.sections}
TAB_KEYS = {t.key for t in TABS}

# Ce que contiendront les sous-onglets prévus (page « bientôt » d'un onglet pas encore construit).
UPCOMING_DESCRIPTIONS = {
    "Prestations": "Le temps passé sur le dossier, par collaborateur et par type de travail.",
    "Pièces": "Tous les documents du client, classés automatiquement (factures, extraits, "
    "statuts, déclarations…), avec recherche et durée de conservation légale.",
    "Courriers et e-mails": "Les échanges avec le client, reliés au dossier, et les modèles de "
    "courrier préremplis.",
    "Signatures": "Envoi de documents à signer (itsme) et suivi des signatures.",
    "Anti-blanchiment": "Le dossier KYC : niveau de risque, vérifications (listes de sanctions), "
    "revue périodique, décisions de l'AMLCO.",
    "Pièces d'identité": "Les cartes d'identité des personnes liées, avec alerte avant expiration "
    "et demande automatique de la nouvelle carte au client.",
    "Déclarations UBO": "Les déclarations au registre UBO et leur confirmation annuelle, "
    "comparées au calcul des bénéficiaires effectifs.",
    "Honoraires": "Les conditions de facturation du client (forfaits, tarifs horaires).",
    "Factures": "Les factures émises au client, envoyées par Peppol, et leur paiement.",
}


def _allowed(section: Section, client: Client) -> bool:
    return section.for_persons if client.is_person else section.for_entities


def sections_for(client: Client) -> list[Section]:
    return [s for s in SECTIONS if _allowed(s, client)]


@dataclass(frozen=True)
class TabView:
    """Onglet tel qu'affiché pour un client donné."""

    key: str
    label: str
    sections: list[Section]
    upcoming: tuple[str, ...]

    @property
    def first(self) -> Section | None:
        return self.sections[0] if self.sections else None


def tabs_for(client: Client) -> list[TabView]:
    return [
        TabView(t.key, t.label, [s for s in t.sections if _allowed(s, client)], t.upcoming)
        for t in TABS
    ]


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
    "relation_add": "relations",
    "relation_edit": "relations",
    "assignments": "team",
    "official_function_add": "public_data",
}
UPCOMING_SECTION = "upcoming"


def section_of(request: HttpRequest) -> str:
    """Rubrique affichée, pour la garder en changeant de client."""
    match = request.resolver_match
    if match is None or match.namespace != "clients" or not match.url_name:
        return DEFAULT_SECTION
    if match.url_name in SECTION_NAMES:
        return match.url_name
    if match.url_name == UPCOMING_SECTION:
        return f"{UPCOMING_SECTION}:{match.kwargs.get('tab', '')}"
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
