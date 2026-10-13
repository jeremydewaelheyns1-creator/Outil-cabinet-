"""Dossier actif : le client choisi en haut de l'écran.

Comme dans un logiciel comptable par dossier, on choisit un client une fois ; il reste
affiché en haut de chaque écran et le menu de gauche présente ses rubriques. Changer de
client garde la rubrique ouverte (on passe de « Relations » d'un client à « Relations »
d'un autre).

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


# Rubriques du dossier, dans l'ordre du menu. Le nom d'URL est dans l'espace « clients ».
SECTIONS: tuple[Section, ...] = (
    Section("detail", "Synthèse"),
    Section("tasks", "Échéances"),
    Section("identity", "Identité et coordonnées"),
    Section("relations", "Relations"),
    Section("ubo", "Bénéficiaires effectifs", for_persons=False),
    Section("team", "Équipe du cabinet"),
    Section("public_data", "BCE et TVA", for_persons=False),
    Section("history", "Historique"),
)
SECTION_NAMES = {s.url_name for s in SECTIONS}

# Rubriques prévues, affichées grisées pour donner la structure du dossier.
UPCOMING = (
    "Documents",
    "Anti-blanchiment",
    "Facturation",
)


def sections_for(client: Client) -> list[Section]:
    return [s for s in SECTIONS if (s.for_persons if client.is_person else s.for_entities)]


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
