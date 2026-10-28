"""Consultation des sites officiels pour une société : BCE, Moniteur belge, Banque Nationale.

Chaque consultation donne un relevé (`OfficialSnapshot`) conservé tel quel. Comparé au relevé
précédent, il révèle ce qui a changé (nouvelle publication, nouvel administrateur, nouveaux
comptes) : un événement `official.changed` est alors enregistré et la synthèse le signale.
Rien n'est modifié dans la fiche : reprendre un administrateur dans les relations reste une
décision du cabinet (un clic, voir `clients.views.official_function_add`).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx
from django.conf import settings
from django.db.models import Max, Q
from django.utils import timezone

from apps.clients.models import Client, Relation
from apps.core import events
from apps.core.models import User

from .models import OfficialSnapshot
from .official_parsers import Function as Function
from .official_parsers import normalize, parse_kbo_functions, parse_moniteur

logger = logging.getLogger(__name__)
Source = OfficialSnapshot.Source
Status = OfficialSnapshot.Status
KEEP = 10  # relevés conservés par client et par source
HEADERS = {"User-Agent": "Outil-cabinet (consultation ponctuelle d'un dossier)"}


@dataclass(frozen=True)
class Fetched:
    status: str
    items: list[dict[str, Any]]
    error: str = ""


def _http() -> httpx.Client:
    return httpx.Client(
        timeout=settings.OFFICIAL_TIMEOUT_SECONDS, headers=HEADERS, follow_redirects=True
    )


# --- Liens publics (toujours disponibles, même sans consultation automatique) --------------


def public_urls(number: str) -> dict[str, str]:
    return {
        Source.KBO: f"https://kbopub.economie.fgov.be/kbopub/toonondernemingps.html"
        f"?ondernemingsnummer={number}&lang=fr",
        Source.MONITEUR: "https://www.ejustice.just.fgov.be/cgi_tsv/list.pl"
        f"?language=fr&btw={number}&page=1&la_search=f&view_numac=",
        Source.NBB: f"https://consult.cbso.nbb.be/consult-enterprise/{number}",
    }


# --- Lecteurs par source ----------------------------------------------------------------------


def _fetch_kbo(number: str, http: httpx.Client) -> Fetched:
    response = http.get(
        settings.KBO_PUBLIC_URL, params={"ondernemingsnummer": number, "lang": "fr"}
    )
    if response.status_code >= 400:
        return Fetched(Status.UNAVAILABLE, [], f"HTTP {response.status_code}")
    functions = parse_kbo_functions(response.text)
    if functions is None:
        return Fetched(Status.UNREADABLE, [], "bloc « Fonctions » introuvable")
    return Fetched(Status.OK, [f.as_dict() for f in functions])


def _fetch_moniteur(number: str, http: httpx.Client) -> Fetched:
    response = http.get(
        settings.MONITEUR_URL,
        params={"language": "fr", "btw": number, "page": "1", "la_search": "f"},
    )
    if response.status_code >= 400:
        return Fetched(Status.UNAVAILABLE, [], f"HTTP {response.status_code}")
    publications = parse_moniteur(response.text, str(response.url))
    if publications is None:
        return Fetched(Status.UNREADABLE, [], "liste des publications introuvable")
    return Fetched(Status.OK, [p.as_dict() for p in publications[:40]])


def _fetch_nbb(number: str, http: httpx.Client) -> Fetched:
    if not settings.NBB_CBSO_KEY:
        return Fetched(Status.NOT_CONFIGURED, [], "clé d'accès de la Banque Nationale absente")
    response = http.get(
        f"{settings.NBB_CBSO_API_URL}/authentic/legalEntity/{number}/references",
        headers={
            "NBB-CBSO-Subscription-Key": settings.NBB_CBSO_KEY,
            "X-Request-Id": str(uuid.uuid4()),
            "Accept": "application/json",
        },
    )
    if response.status_code == 404:
        return Fetched(Status.OK, [])
    if response.status_code >= 400:
        return Fetched(Status.UNAVAILABLE, [], f"HTTP {response.status_code}")
    data = response.json()
    if not isinstance(data, list):
        return Fetched(Status.UNREADABLE, [], "réponse inattendue")
    items = [_filing(d) for d in data if isinstance(d, dict) and d.get("ReferenceNumber")]
    items.sort(key=lambda f: (f["exercise_end"], f["deposit_date"]), reverse=True)
    return Fetched(Status.OK, items[:30])


def _filing(data: dict[str, Any]) -> dict[str, Any]:
    dates = data.get("ExerciseDates") or {}
    return {
        "reference": str(data.get("ReferenceNumber", "")),
        "deposit_date": str(data.get("DepositDate") or "")[:10],
        "exercise_start": str(dates.get("startDate") or "")[:10],
        "exercise_end": str(dates.get("endDate") or "")[:10],
        "model": str(data.get("ModelType") or ""),
        "deposit_type": str(data.get("DepositType") or ""),
        "general_assembly": str(data.get("GeneralAssemblyDate") or "")[:10],
    }


FETCHERS: dict[str, Callable[[str, httpx.Client], Fetched]] = {
    Source.KBO: _fetch_kbo,
    Source.MONITEUR: _fetch_moniteur,
    Source.NBB: _fetch_nbb,
}


def _key(source: str, item: dict[str, Any]) -> str:
    if source == Source.KBO:
        name = normalize(f"{item.get('name', '')} {item.get('first_name', '')}")
        return f"{item.get('role')}|{name}|{item.get('enterprise_number')}"
    if source == Source.MONITEUR:
        return str(item.get("pdf_url") or item.get("number"))
    return str(item.get("reference"))


# --- Consultation -------------------------------------------------------------------------


def latest(client: Client, source: str, *, ok_only: bool = False) -> OfficialSnapshot | None:
    query = client.official_snapshots.filter(source=source)
    if ok_only:
        query = query.filter(status=Status.OK)
    return query.order_by("-fetched_at").first()


def refresh(
    client: Client,
    source: str,
    *,
    user: User | None = None,
    http: httpx.Client | None = None,
) -> OfficialSnapshot:
    """Consulte une source pour ce client et enregistre le relevé, quel qu'en soit le résultat."""
    if not client.enterprise_number:
        raise ValueError("Ce client n'a pas de numéro d'entreprise.")
    previous = latest(client, source, ok_only=True)
    owns = http is None
    session = http or _http()
    try:
        fetched = FETCHERS[source](client.enterprise_number, session)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Site officiel %s indisponible : %s", source, type(exc).__name__)
        fetched = Fetched(Status.UNAVAILABLE, [], type(exc).__name__)
    finally:
        if owns:
            session.close()
    snapshot = OfficialSnapshot.objects.create(
        client=client,
        source=source,
        status=fetched.status,
        items=fetched.items,
        error=fetched.error[:200],
        fetched_by=user,
    )
    old = client.official_snapshots.filter(source=source).order_by("-fetched_at")[KEEP:]
    OfficialSnapshot.objects.filter(pk__in=list(old.values_list("pk", flat=True))).delete()
    if snapshot.ok and previous is not None:
        known = {_key(source, i) for i in previous.items}
        new = [i for i in snapshot.items if _key(source, i) not in known]
        if new:
            events.emit(
                "official.changed",
                subject=client,
                actor=user,
                payload={"source": source, "count": len(new)},
            )
    return snapshot


def refresh_all(client: Client, *, user: User | None = None) -> list[OfficialSnapshot]:
    with _http() as session:
        return [refresh(client, s, user=user, http=session) for s in Source.values]


def refresh_due(limit: int | None = None) -> int:
    """Passage automatique (run_jobs) : les sociétés actives les moins récemment consultées."""
    if not settings.OFFICIAL_AUTO_REFRESH:
        return 0
    limit = limit or settings.OFFICIAL_REFRESH_BATCH
    threshold = timezone.now() - timedelta(days=settings.OFFICIAL_REFRESH_DAYS)
    due = (
        Client.objects.exclude(kind=Client.Kind.PERSON)
        .filter(
            status=Client.Status.ACTIVE, enterprise_number__isnull=False, deleted_at__isnull=True
        )
        .annotate(last=Max("official_snapshots__fetched_at"))
        .filter(Q(last__isnull=True) | Q(last__lt=threshold))
        .order_by("last", "pk")[:limit]
    )
    count = 0
    for client in due:
        refresh_all(client)
        count += 1
    return count


# --- Fonctions BCE comparées aux relations --------------------------------------------------


ROLE_MAP = (
    ("liquidat", Relation.Role.LIQUIDATOR),
    ("representant permanent", Relation.Role.PERMANENT_REPRESENTATIVE),
    ("delegue", Relation.Role.MANAGING_DIRECTOR),
    ("gestion journaliere", Relation.Role.MANAGING_DIRECTOR),
    ("gerant", Relation.Role.MANAGER),
    ("administrateur", Relation.Role.DIRECTOR),
)


def role_for(label: str) -> str:
    lowered = normalize(label)
    return next((role for key, role in ROLE_MAP if key in lowered), Relation.Role.OTHER)


NOT_FUNCTIONS = (Relation.Role.SHAREHOLDER, Relation.Role.BENEFICIAL_OWNER, Relation.Role.SPOUSE)


@dataclass(frozen=True)
class FunctionCheck:
    index: int
    function: Function
    role: str
    relation: Relation | None

    @property
    def matched(self) -> bool:
        return self.relation is not None


def same_person(function: Function, person: Client) -> bool:
    wanted = set(normalize(function.display_name).split())
    have = set(normalize(f"{person.name} {person.first_name}").split())
    return bool(wanted) and wanted == have


def _matches(function: Function, person: Client) -> bool:
    if function.enterprise_number:
        return person.enterprise_number == function.enterprise_number
    return person.is_person and same_person(function, person)


def compare_functions(client: Client, snapshot: OfficialSnapshot | None) -> list[FunctionCheck]:
    """Chaque fonction lue à la BCE, avec la relation correspondante de la fiche s'il y en a une."""
    if snapshot is None or not snapshot.ok:
        return []
    # Seules les fonctions comptent : être actionnaire ne fait pas de quelqu'un un gérant.
    relations = list(
        Relation.objects.current()
        .filter(entity=client)
        .exclude(role__in=NOT_FUNCTIONS)
        .select_related("person")
    )
    checks = []
    for index, data in enumerate(snapshot.items):
        function = Function(**{k: data.get(k, "") for k in Function.__dataclass_fields__})
        relation = next((r for r in relations if _matches(function, r.person)), None)
        checks.append(FunctionCheck(index, function, role_for(function.role), relation))
    return checks
