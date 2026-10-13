"""Dossier actif : le client choisi en haut de l'écran.

Comme dans un logiciel comptable par dossier, on choisit un client une fois ; il reste
affiché en haut de l'écran. Dans un dossier, l'écran ne montre que lui : un en-tête fixe, des
onglets (Synthèse, Fiche, Travail, Documents, Conformité, Facturation) et leurs
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
DETAIL = Section("detail", "Synthèse")
HISTORY = Section("history", "Historique")


@dataclass(frozen=True)
class Tab:
    key: str
    label: str
    sections: tuple[Section, ...] = ()
    upcoming: tuple[str, ...] = ()  # sous-onglets prévus, affichés grisés


TABS: tuple[Tab, ...] = (
    Tab("synthese", "Synthèse", (DETAIL,)),
    Tab(
        "fiche",
        "Fiche",
        (
            Section("identity", "Identité et coordonnées"),
            Section("relations", "Relations"),
            Section("ubo", "Bénéficiaires effectifs", for_persons=False),
            Section("public_data", "BCE et TVA", for_persons=False),
            Section("team", "Équipe du cabinet"),
        ),
    ),
    Tab("travail", "Travail", (Section("tasks", "Échéances"),), ("Prestations",)),
    Tab("documents", "Documents", (), ("Pièces", "Courriers et e-mails", "Signatures")),
    Tab(
        "conformite",
        "Conformité",
        (),
        ("Anti-blanchiment", "Pièces d'identité", "Déclarations UBO"),
    ),
    Tab("facturation", "Facturation", (), ("Honoraires", "Factures")),
)

SECTIONS: tuple[Section, ...] = (*(s for t in TABS for s in t.sections), HISTORY)
SECTION_NAMES = {s.url_name for s in SECTIONS}
TAB_OF = {s.url_name: t.key for t in TABS for s in t.sections}


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
ACTION_SECTIONS = {
    "edit": "identity",
    "relation_add": "relations",
    "relation_edit": "relations",
    "assignments": "team",
}


def section_of(request: HttpRequest) -> str:
    """Rubrique affichée, pour la garder en changeant de client."""
    match = request.resolver_match
    if match is None or match.namespace != "clients" or not match.url_name:
        return "detail"
    if match.url_name in SECTION_NAMES:
        return match.url_name
    return ACTION_SECTIONS.get(match.url_name, "detail")
