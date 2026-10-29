"""Délais prolongés par le SPF Finances (D-089).

Le SPF ne publie pas de calendrier lisible par une machine : il annonce ses prolongations
(« la date limite de dépôt de la déclaration TVA du 3e trimestre est reportée au … ») dans des
communiqués. L'outil :
1. **surveille** chaque jour deux flux officiels publics (communiqués du gouvernement fédéral,
   où publie le SPF Finances ; actualités de l'ITAA, qui relaie chaque décision du SPF). Rien du
   cabinet n'est envoyé : simple lecture de pages publiques ;
2. **repère** les articles qui parlent de délai ET d'impôt (mots lisibles, aucune IA) et
   prévient les administrateurs (cloche) — l'article est « à vérifier » ;
3. un administrateur **encode** la prolongation (échéance, période, nouvelle date) en la
   choisissant dans une liste : c'est l'humain qui décide ; il peut aussi l'encoder sans
   article (bouton manuel) ;
4. les échéances concernées sont **déplacées** (et la ligne TVA suit, `task.rescheduled`) ; la
   génération quotidienne respecte la prolongation ; chacun voit un **petit message** à sa
   prochaine ouverture de l'outil, jusqu'à ce qu'il clique « Compris ».
Annuler une prolongation remet l'ancienne date.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime

import httpx
from defusedxml import ElementTree
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags

from apps.core import events
from apps.core.models import Notification, User
from apps.core.text import normalize_text

from .models import DeadlineExtension, DeadlineNotice, Task

logger = logging.getLogger(__name__)

# Il faut au moins un mot de chaque groupe (texte sans accents, en minuscules).
DELAY_WORDS = (
    "prolong", "report", "delai supplementaire", "tolerance", "date limite", "delai de depot",
    "delai d'introduction", "delai de paiement", "decale",
)  # fmt: skip
TAX_WORDS = (
    "tva", "ipp", "isoc", "impot des societes", "impot des personnes physiques", "biztax",
    "tax-on-web", "listing", "precompte", "declaration", "ubo",
)  # fmt: skip
RECENT_DAYS = 30  # au premier passage, on ne remonte pas plus loin


def mentions_deadline(text: str) -> bool:
    plain = normalize_text(text)
    return any(w in plain for w in DELAY_WORDS) and any(w in plain for w in TAX_WORDS)


@dataclass(frozen=True)
class Item:
    title: str
    url: str
    excerpt: str
    published_at: datetime | None


def parse_feed(content: bytes) -> list[Item]:
    """Flux RSS 2.0 (lecture sûre : defusedxml)."""
    root = ElementTree.fromstring(content)
    items = []
    for node in root.iter("item"):
        title = (node.findtext("title") or "").strip()
        url = (node.findtext("link") or "").strip()
        if not title or not url.startswith("https://"):
            continue
        description = strip_tags(node.findtext("description") or "").replace("&nbsp;", " ")
        published: datetime | None = None
        raw = node.findtext("pubDate")
        if raw:
            try:
                published = parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                published = None
        items.append(Item(title[:300], url[:500], " ".join(description.split())[:1000], published))
    return items


def watch(http: httpx.Client | None = None) -> int:
    """Passage quotidien : nouveaux articles à vérifier (retourne leur nombre)."""
    if not settings.DEADLINE_WATCH:
        return 0
    own = http is None
    http = http or httpx.Client(
        timeout=settings.OFFICIAL_TIMEOUT_SECONDS, follow_redirects=True,
        headers={"User-Agent": "Outil-cabinet (suivi des délais fiscaux)"},
    )  # fmt: skip
    since = timezone.now() - timedelta(days=RECENT_DAYS)
    found: list[DeadlineNotice] = []
    try:
        for name, url in settings.DEADLINE_SOURCES:
            try:
                response = http.get(url)
                response.raise_for_status()
                items = parse_feed(response.content)
            except (httpx.HTTPError, ElementTree.ParseError, ValueError) as error:
                # Source momentanément indisponible ou changée : on réessaiera demain.
                logger.warning(
                    "Délais du SPF : source %s illisible (%s)", name, type(error).__name__
                )
                continue
            for item in items:
                if item.published_at is not None and item.published_at < since:
                    continue
                if not mentions_deadline(f"{item.title} {item.excerpt}"):
                    continue
                notice, created = DeadlineNotice.objects.get_or_create(
                    url=item.url,
                    defaults={"source": name, "title": item.title, "excerpt": item.excerpt,
                              "published_at": item.published_at},
                )  # fmt: skip
                if created:
                    found.append(notice)
    finally:
        if own:
            http.close()
    if found:
        _notify_admins(found)
    return len(found)


def _notify_admins(found: list[DeadlineNotice]) -> None:
    from django.urls import reverse

    link = reverse("tasks:extensions")
    for user in User.objects.filter(is_staff=True, is_active=True):
        for notice in found:
            Notification.objects.get_or_create(
                user=user, key=f"delais-spf:{notice.pk}",
                defaults={"title": "Délai fiscal peut-être prolongé : article à vérifier",
                          "lines": [notice.title[:200]], "link": link},
            )  # fmt: skip


# --- Encoder, appliquer, annuler -------------------------------------------------------------


@dataclass(frozen=True)
class Deadline:
    """Une échéance commune (même règle, même période, même date) : ce qu'on peut prolonger."""

    kind: str
    period_key: str
    label: str
    due_date: date
    count: int

    @property
    def value(self) -> str:
        return f"{self.kind}|{self.period_key}|{self.due_date.isoformat()}"


def deadlines(today: date | None = None) -> list[Deadline]:
    """Échéances récentes et à venir (60 jours en arrière, 8 mois en avant), regroupées."""
    today = today or timezone.localdate()
    rows = Task.objects.filter(
        generated=True, due_date__gte=today - timedelta(days=60),
        due_date__lte=today + timedelta(days=240),
    ).values_list("kind", "period_key", "due_date", "title")  # fmt: skip
    groups: dict[tuple[str, str, date], list[str]] = {}
    for kind, period_key, due_date, title in rows:
        groups.setdefault((kind, period_key, due_date), []).append(title)
    return sorted(
        (Deadline(kind, key, min(titles), due, len(titles))
         for (kind, key, due), titles in groups.items()),
        key=lambda d: (d.due_date, d.label),
    )  # fmt: skip


def find(value: str, today: date | None = None) -> Deadline | None:
    return next((d for d in deadlines(today) if d.value == value), None)


def _move(kind: str, period_key: str, old: date, new: date) -> int:
    moved = 0
    tasks = Task.objects.filter(generated=True, kind=kind, period_key=period_key, due_date=old)
    for task in tasks.select_related("client"):
        task.due_date = new
        task.save(update_fields=["due_date", "updated_at"])
        events.emit(
            "task.rescheduled", subject=task.client,
            payload={"tache": task.pk, "avant": old.isoformat(), "apres": new.isoformat()},
        )  # fmt: skip
        moved += 1
    return moved


def create(
    deadline: Deadline,
    new_date: date,
    *,
    user: User | None,
    note: str = "",
    source_url: str = "",
    notice: DeadlineNotice | None = None,
) -> DeadlineExtension:
    if new_date == deadline.due_date:
        raise ValueError("La nouvelle date est la même que la date limite actuelle.")
    with transaction.atomic():
        extension = DeadlineExtension.objects.create(
            kind=deadline.kind, period_key=deadline.period_key, label=deadline.label[:200],
            previous_date=deadline.due_date, new_date=new_date, note=note.strip()[:300],
            source_url=source_url.strip()[:500], notice=notice, created_by=user,
        )  # fmt: skip
        if user is not None:
            extension.seen_by.add(user)  # celui qui l'encode n'a pas besoin du message
        if notice is not None:
            notice.status = DeadlineNotice.Status.HANDLED
            notice.handled_at, notice.handled_by = timezone.now(), user
            notice.save(update_fields=["status", "handled_at", "handled_by"])
        moved = _move(deadline.kind, deadline.period_key, deadline.due_date, new_date)
    events.emit(
        "deadline.extended", actor=user,
        payload={"echeance": deadline.kind, "periode": deadline.period_key,
                 "avant": deadline.due_date.isoformat(), "apres": new_date.isoformat(),
                 "taches": moved},
    )  # fmt: skip
    return extension


def cancel(extension: DeadlineExtension, *, user: User | None) -> int:
    """Erreur d'encodage : les échéances reprennent leur ancienne date."""
    with transaction.atomic():
        moved = _move(
            extension.kind, extension.period_key, extension.new_date, extension.previous_date
        )
        payload = {"echeance": extension.kind, "periode": extension.period_key, "taches": moved}
        extension.delete()
    events.emit("deadline.extension_cancelled", actor=user, payload=payload)
    return moved


def overrides() -> dict[tuple[str, str, date], date]:
    """Pour la génération : (règle, période, date de la règle) → date prolongée."""
    return {
        (e.kind, e.period_key, e.previous_date): e.new_date for e in DeadlineExtension.objects.all()
    }


def unseen_for(user: User) -> list[DeadlineExtension]:
    """Prolongations des 60 derniers jours que cette personne n'a pas encore vues."""
    since = timezone.now() - timedelta(days=60)
    return list(DeadlineExtension.objects.filter(created_at__gte=since).exclude(seen_by=user)[:5])
