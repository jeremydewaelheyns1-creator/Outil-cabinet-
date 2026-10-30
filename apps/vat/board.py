"""« Mes déclarations TVA » : la page ouverte par « Ouvrir mes échéances » pendant le mois TVA
(D-109). Un cadre par dossier, avec la ligne de l'onglet « Déclaration TVA » de la période :
mêmes cases, mêmes données (cocher ici coche là-bas). Seulement MES dossiers (ceux de
l'Accueil : où je suis affecté, plus les hybrides que j'ai pris).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from apps.core import accueil
from apps.core.models import User
from apps.tasks.models import Task
from apps.timesheet.models import TimeEntry, hours_label, minutes_between

from . import services
from .models import Column, Status, VatFiling

FILTERS = {
    "": "Toutes",
    "pas-commencees": "Pas commencées",
    "en-cours": "En cours",
    "deposees": "Déposées",
}
GROUPS = (("todo", "À commencer"), ("doing", "En cours"), ("done", "Terminées"))


@dataclass
class Card:
    row: services.Row
    task: Task
    group: str  # todo / doing / done
    tag: str
    tone: str  # rouge / orange / vert / gris
    minutes: int = 0

    @property
    def filing(self) -> VatFiling:
        return self.row.filing

    @property
    def filed(self) -> bool:
        return self.row.cell(Column.FILED).status in (Status.DONE, Status.NOT_NEEDED)

    @property
    def time_label(self) -> str:
        return hours_label(self.minutes)


@dataclass
class Board:
    campaign: accueil.Campaign | None
    cards: list[Card] = field(default_factory=list)

    def groups(self, wanted: str) -> list[tuple[str, list[Card]]]:
        shown = [c for c in self.cards if _matches(c, wanted)]
        return [(label, [c for c in shown if c.group == key]) for key, label in GROUPS]

    def count(self, wanted: str) -> int:
        return sum(1 for c in self.cards if _matches(c, wanted))


def _matches(card: Card, wanted: str) -> bool:
    if wanted == "pas-commencees":
        return card.group == "todo"
    if wanted == "en-cours":
        return card.group == "doing"
    if wanted == "deposees":
        return card.filed
    return True


def _campaign(user: User, today: date) -> accueil.Campaign | None:
    """La campagne TVA en cours (celle de l'Accueil), sinon la prochaine, sinon la dernière."""
    tasks = list(
        Task.objects.filter(
            client__in=accueil.my_clients(user),
            kind__in=services.VAT_RULES,
            due_date__gte=today - timedelta(days=60),
            due_date__lte=today + timedelta(days=120),
        )
        .select_related("client")
        .order_by("due_date")
    )
    found = [c for c in accueil.campaigns(tasks) if c.family.code == "tva"]
    for campaign in found:
        campaign.today = today
    active = [c for c in found if c.starts <= today <= c.deadline]
    later = [c for c in found if c.deadline > today]
    if active:
        return active[0]
    if later:
        return later[0]
    return found[-1] if found else None


def _state(row: services.Row, task: Task, today: date) -> tuple[str, str, str]:
    """Groupe, étiquette et couleur d'un cadre."""
    statuses = {c.column: c for c in row.cells}
    filed = statuses[Column.FILED].status in (Status.DONE, Status.NOT_NEEDED)
    started = any(c.status != Status.TODO and not c.never for c in row.cells)
    if row.complete:
        return "done", "terminée", "vert"
    if filed:
        return "doing", "déposée · client à informer", "orange"
    days = (task.due_date - today).days
    if days < 0:
        late = -days
        return (
            ("doing" if started else "todo"),
            f"en retard de {late} jour{'s' if late > 1 else ''}",
            "rouge",
        )
    if not started:
        return "todo", "pas commencée", "gris"
    left = "aujourd'hui" if days == 0 else f"encore {days} jour{'s' if days > 1 else ''}"
    return "doing", left, "orange" if days <= 7 else "gris"


def _filing(task: Task) -> VatFiling:
    filing: VatFiling | None = VatFiling.objects.filter(task=task).first()
    if filing is not None:
        return filing
    year, _, part = task.period_key.partition("-")
    if part.startswith("T"):
        p = services.period(int(year), quarter=int(part[1:]))
    else:
        p = services.period(int(year), month=int(part))
    return services.filing_for(task.client, p)


def _my_minutes(user: User, cards: list[Card]) -> None:
    """Mon temps « TVA » sur chaque dossier, depuis le début de la période déclarée."""
    if not cards:
        return
    since = min(c.filing.period_start for c in cards)
    entries = TimeEntry.objects.filter(
        user=user,
        client__in=[c.filing.client_id for c in cards],
        activity=TimeEntry.Activity.VAT,
        day__gte=since,
    ).values_list("client_id", "day", "start", "end")
    totals: dict[int, int] = {}
    for client_id, day, start, end in entries:
        for card in cards:
            if card.filing.client_id == client_id and day >= card.filing.period_start:
                totals[client_id] = totals.get(client_id, 0) + minutes_between(start, end)
                break
    for card in cards:
        card.minutes = totals.get(card.filing.client_id, 0)


def build(user: User, today: date) -> Board:
    campaign = _campaign(user, today)
    board = Board(campaign)
    if campaign is None:
        return board
    for task in sorted(campaign.tasks, key=lambda t: (t.due_date, t.client.name)):
        if task.status == Task.Status.NOT_APPLICABLE or not task.period_key:
            continue
        filing = _filing(task)
        filing = (
            VatFiling.objects.select_related(
                "client", "xml", "pdf", "ic_xml", "ic_pdf", "manager", "assistant"
            )
            .prefetch_related("cells__by", "messages")
            .get(pk=filing.pk)
        )
        row = services.row_for(filing)
        group, tag, tone = _state(row, task, today)
        board.cards.append(Card(row, task, group, tag, tone))
    _my_minutes(user, board.cards)
    return board


def card_for(filing: VatFiling, user: User, today: date) -> Card:
    """Un seul cadre, redessiné après un clic sur une case."""
    row = services.row_for(filing)
    task = filing.task or Task(client=filing.client, due_date=filing.due_date or today)
    group, tag, tone = _state(row, task, today)
    card = Card(row, task, group, tag, tone)
    _my_minutes(user, [card])
    return card
