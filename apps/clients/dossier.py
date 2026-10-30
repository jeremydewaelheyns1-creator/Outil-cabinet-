"""Dossier actif : le client choisi en haut de l'écran.

Comme dans un logiciel comptable par dossier, on choisit un client une fois ; il reste
affiché en haut de l'écran. Dans un dossier, l'écran ne montre que lui (D-026) : un en-tête
fixe, en haut les onglets du travail fréquent (Clôture, Déclaration TVA, Versements
anticipés, Documents), à gauche un panneau « paperasse » comme FID-Manager (Fiche, Organisation,
Suivi, Conformité, Facturation), chaque page à un clic. Ouvrir un dossier mène toujours à
« Identité et coordonnées » (D-028).

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
    slug: str = ""  # page générique : à construire (WORK) ou dossier d'archives (ARCHIVE)
    count: str = ""  # compteur affiché à côté (clé de `counts`)
    # Page qui existe mais n'a pas d'entrée dans le panneau : on y arrive par un lien (D-105).
    hidden: bool = False
    # Réservée à qui a ce droit (ex. heures prestées : vue de l'administrateur, D-107).
    capability: str = ""

    @property
    def key(self) -> str:
        """Identifiant de la page affichée (nom d'URL, ou « work:<slug> », « archive:<slug> »)."""
        return f"{self.url_name}:{self.slug}" if self.slug else self.url_name

    @property
    def is_folder(self) -> bool:
        return self.url_name == ARCHIVE


@dataclass(frozen=True)
class Group:
    label: str
    sections: tuple[Section, ...]


WORK = "work"  # page « à construire » (onglets du haut, entrées prévues à gauche)
ARCHIVE = "archive"  # dossier d'archives (documents du passé, D-031)

# D-026 — En haut : le travail le plus fréquent. Contenu défini un par un avec Jeremy.
TOP: tuple[Section, ...] = (
    Section(WORK, "Clôture", slug="cloture"),
    Section("vat", "Déclaration TVA", vat_only=True),
    Section(WORK, "Versements anticipés", slug="versements-anticipes"),
    Section("documents", "Documents"),
)

# À gauche : la « paperasse ». Allégé avec Jeremy (D-105) : pas une copie de FID-Manager.
# Les pages cachées (`hidden`) existent toujours et s'ouvrent par un lien (en-tête, Archives…).
SIDE: tuple[Group, ...] = (
    Group("Fiche", (Section("identity", "Identité et coordonnées"),)),
    Group(
        "Organisation",
        (
            # D-106 : encodés depuis Documents (Identification des mandataires, UBO).
            Section("mandates", "Mandataires", count="mandates", hidden=True),
            Section("shareholders", "Actionnaires", count="shareholders", hidden=True),
        ),
    ),
    # D-031, D-105 — Une seule entrée « Archives » : un classeur par année puis par sujet.
    # Les anciens dossiers restent les sujets du classeur (et leurs adresses y mènent).
    Group(
        "Archives",
        (
            Section("archives", "Archives", count="archives"),
            Section(ARCHIVE, "Légal et statuts", slug="legal", for_persons=False, hidden=True),
            Section(ARCHIVE, "Moniteur belge", slug="moniteur", for_persons=False, hidden=True),
            Section("annual_accounts", "Comptes annuels (BNB)", for_persons=False, hidden=True),
            Section(ARCHIVE, "ISOC", slug="isoc", for_persons=False, hidden=True),
            Section(ARCHIVE, "IPP", slug="ipp", for_entities=False, hidden=True),
            Section(ARCHIVE, "TVA", slug="tva", hidden=True),
            Section(ARCHIVE, "Administratif", slug="administratif", hidden=True),
            Section(ARCHIVE, "Courriels", slug="courriels", hidden=True),
        ),
    ),
    # Échéances (badge « en retard » de l'en-tête) et Historique (lien en bas de la fiche).
    Group(
        "Suivi",
        (
            Section("tasks", "Échéances", count="overdue", hidden=True),
            Section("history", "Historique", hidden=True),
        ),
    ),
    Group(
        "Facturation",
        (
            # D-107 : les heures de chacun sur un dossier, c'est pour l'administrateur.
            Section("time_spent", "Heures prestées", capability="timesheet.all"),
            Section(WORK, "Honoraires", slug="honoraires", hidden=True),
            # Factures du cabinet déposées : reconnues et rangées ici (D-105).
            Section(ARCHIVE, "Factures", slug="factures"),
        ),
    ),
)

SECTIONS: tuple[Section, ...] = (*TOP, *(s for g in SIDE for s in g.sections))
SECTION_NAMES = {s.url_name for s in SECTIONS if not s.slug}
WORK_PAGES = {s.slug: s for s in SECTIONS if s.url_name == WORK}
ARCHIVE_FOLDERS = {s.slug: s for s in SECTIONS if s.url_name == ARCHIVE}
# Sujets du classeur « Archives » (tous les dossiers d'archives sauf les factures, D-105).
CLASSEUR_FOLDERS = ("tva", "isoc", "ipp", "comptes", "legal", "moniteur", "administratif",
                    "courriels")  # fmt: skip
# Comptes annuels déposés (PDF, XBRL) : rangés à part, affichés sur la page « Comptes annuels
# (BNB) » sous les dépôts lus à la Banque Nationale (D-098).
ACCOUNTS_FOLDER = "comptes"
ACCOUNTS_SECTION = next(s for s in SECTIONS if s.url_name == "annual_accounts")
DOCUMENT_FOLDERS: dict[str, Section] = {**ARCHIVE_FOLDERS, ACCOUNTS_FOLDER: ACCOUNTS_SECTION}


def folder_url(client_pk: int, folder: str) -> str:
    """Page où se trouvent les documents d'un dossier d'archives."""
    from django.urls import reverse

    if folder in CLASSEUR_FOLDERS and folder != "moniteur":
        return f"{reverse('clients:archives', args=[client_pk])}?sujet={folder}"  # D-105
    return reverse("clients:archive", args=[client_pk, folder])


def folders_for(client: Client) -> list[tuple[str, Section]]:
    """Dossiers où ranger un document de ce client (archives et comptes annuels)."""
    return [(slug, s) for slug, s in DOCUMENT_FOLDERS.items() if _allowed(s, client)]


# Pages « Organisation » : quels rôles de relation chacune montre.
# D-033 — Cases de l'onglet Documents (ce qui est en cours ; le passé va aux Archives).
@dataclass(frozen=True)
class DocumentCase:
    slug: str
    label: str
    description: str
    for_persons: bool = True
    url_name: str = "document_case"  # page dédiée si elle existe déjà (UBO)


# Une case par ligne de la rubrique « Loi anti-blanchiment » de FID-Manager (D-038).
DOCUMENT_CASES: tuple[DocumentCase, ...] = (
    DocumentCase(
        "a-recevoir",
        "À recevoir",
        "Les demandes envoyées au client, jusqu'à leur réception, avec les relances.",
    ),
    DocumentCase(
        "lettre-de-mission",
        "Lettre de mission",
        "La lettre de mission signée avec le client.",
    ),
    DocumentCase(
        "pieces-identite",
        "Cartes d'identité",
        "Les cartes des mandataires et des actionnaires, avec alerte avant expiration et "
        "demande automatique de la nouvelle carte.",
    ),
    DocumentCase(
        "declaration-ubo",
        "Déclaration des bénéficiaires effectifs",
        "La déclaration signée par le client.",
        for_persons=False,
    ),
    DocumentCase(
        "identification-client",
        "Identification du client",
        "La fiche d'identification du client.",
    ),
    DocumentCase(
        "identification-mandataires",
        "Identification des mandataires",
        "Une fiche d'identification par mandataire (personne ou société).",
        for_persons=False,
    ),
    DocumentCase("procuration", "Procuration", "La procuration donnée au cabinet."),
    DocumentCase(
        "fiche-risque",
        "Fiche de détermination du niveau de risque",
        "Le niveau de risque du client et sa date de revue.",
    ),
    DocumentCase(
        "ubo",
        "UBO",
        "Les bénéficiaires effectifs calculés et l'extrait du registre UBO.",
        for_persons=False,
        url_name="ubo",
    ),
)
DOCUMENT_CASE_SLUGS = {c.slug: c for c in DOCUMENT_CASES}


def document_cases_for(client: Client) -> list[DocumentCase]:
    return [c for c in DOCUMENT_CASES if c.for_persons or not client.is_person]


def case_url(client_pk: int, case: DocumentCase) -> str:
    from django.urls import reverse

    if case.url_name == "document_case":
        return reverse("clients:document_case", args=[client_pk, case.slug])
    return reverse(f"clients:{case.url_name}", args=[client_pk])


RELATION_PAGES: dict[str, tuple[str, ...]] = {
    "mandates": (*Relation.MANAGEMENT_ROLES, Relation.Role.PERMANENT_REPRESENTATIVE),
    "shareholders": (Relation.Role.SHAREHOLDER,),
}


def page_for_role(role: str) -> str:
    """Page où revenir après avoir enregistré une relation de ce rôle."""
    if role == Relation.Role.BENEFICIAL_OWNER:
        return "ubo"
    return next((page for page, roles in RELATION_PAGES.items() if role in roles), "mandates")


def _allowed(section: Section, client: Client) -> bool:
    if section.vat_only and client.vat_status != Client.VatStatus.SUBJECT:
        return False
    return section.for_persons if client.is_person else section.for_entities


def sections_for(client: Client) -> list[Section]:
    return [s for s in SECTIONS if _allowed(s, client)]


def top_for(client: Client) -> list[Section]:
    return [s for s in TOP if _allowed(s, client)]


def side_for(client: Client, user: User | None = None) -> list[Group]:
    def shown(s: Section) -> bool:
        if s.hidden or not _allowed(s, client):
            return False
        return not s.capability or (user is not None and user.has_capability(s.capability))

    groups = [Group(g.label, tuple(s for s in g.sections if shown(s))) for g in SIDE]
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
    "assignments": "identity",
    "bce_apply": "identity",
    "bce_refresh": "identity",
    "official_function_add": "mandates",
    # Onglet Documents (D-033) : les cases s'ouvrent sous l'onglet.
    "document_case": "documents",
    "document_viewer_page": "documents",
    "ubo": "documents",
    "risk_sheet": "documents",
    "letter_prepare": "documents",
    "spf_mandate_request": "documents",
}


def section_of(request: HttpRequest) -> str:
    """Rubrique affichée, pour la garder en changeant de client."""
    match = request.resolver_match
    if match is None or match.namespace != "clients" or not match.url_name:
        return DEFAULT_SECTION
    if match.url_name in SECTION_NAMES:
        return match.url_name
    if match.url_name in (WORK, ARCHIVE):
        return f"{match.url_name}:{match.kwargs.get('slug', '')}"
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
