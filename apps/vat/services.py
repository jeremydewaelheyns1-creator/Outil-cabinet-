"""La grille TVA d'un client : lignes, cases, et lien avec les échéances (D-040)."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.clients.models import Assignment, Client
from apps.core import events
from apps.core.models import User
from apps.tasks.models import Task
from apps.tasks.rules import MONTHS_FR

from .models import (
    COLUMN_HEADERS,
    FINISHED,
    Column,
    Status,
    VatCell,
    VatFiling,
    VatNever,
)

# Échéances (règles de config/taches/regles.yaml) qui correspondent à une ligne de la grille.
VAT_RULES = {
    "tva_mensuelle": VatFiling.Periodicity.MONTHLY,
    "tva_trimestrielle": VatFiling.Periodicity.QUARTERLY,
}


@dataclass(frozen=True)
class Period:
    key: str
    label: str
    start: date
    end: date
    periodicity: str


def period(year: int, *, month: int | None = None, quarter: int | None = None) -> Period:
    """Même code et même libellé que les échéances (« 2026-T3 », « 3e trimestre 2026 »)."""
    if quarter is not None:
        if not 1 <= quarter <= 4:
            raise ValueError("Trimestre invalide.")
        first = 3 * quarter - 2
        label = "1er" if quarter == 1 else f"{quarter}e"
        return Period(
            f"{year}-T{quarter}",
            f"{label} trimestre {year}",
            date(year, first, 1),
            date(year, first + 2, calendar.monthrange(year, first + 2)[1]),
            VatFiling.Periodicity.QUARTERLY,
        )
    if month is None or not 1 <= month <= 12:
        raise ValueError("Mois invalide.")
    return Period(
        f"{year}-{month:02d}",
        f"{MONTHS_FR[month]} {year}",
        date(year, month, 1),
        date(year, month, calendar.monthrange(year, month)[1]),
        VatFiling.Periodicity.MONTHLY,
    )


def _team(client: Client) -> dict[str, User]:
    return {a.role: a.user for a in client.assignments.select_related("user")}


def filing_for(client: Client, p: Period) -> VatFiling:
    """La ligne de cette période (créée si besoin, reliée à son échéance si elle existe)."""
    team = _team(client)
    filing, _ = VatFiling.objects.get_or_create(
        client=client,
        period_key=p.key,
        defaults={
            "period_label": p.label,
            "period_start": p.start,
            "period_end": p.end,
            "periodicity": p.periodicity,
            "manager": team.get(Assignment.Role.MANAGER),
            "assistant": team.get(Assignment.Role.ASSISTANT),
        },
    )
    if filing.task_id is None:
        task = Task.objects.filter(
            client=client, kind__in=VAT_RULES, period_key=p.key, vat_filing__isnull=True
        ).first()
        if task is not None:
            filing.task, filing.due_date = task, task.due_date
            filing.save(update_fields=["task", "due_date"])
    return filing


def ensure_filings(client: Client, today: date | None = None) -> None:
    """Une ligne pour chaque échéance TVA dont la période a commencé."""
    today = today or timezone.localdate()
    tasks = Task.objects.filter(
        client=client, kind__in=VAT_RULES, period_start__lte=today, vat_filing__isnull=True
    ).exclude(period_key="")
    for task in tasks:
        year, _, part = task.period_key.partition("-")
        if part.startswith("T"):
            p = period(int(year), quarter=int(part[1:]))
        else:
            p = period(int(year), month=int(part))
        filing_for(client, p)


@dataclass(frozen=True)
class Cell:
    column: str
    header: str
    label: str
    status: str
    status_label: str
    on: date | None
    by: User | None
    comment: str
    never: bool

    @property
    def css(self) -> str:
        return "never" if self.never else self.status


@dataclass(frozen=True)
class Row:
    filing: VatFiling
    cells: list[Cell]

    @property
    def complete(self) -> bool:
        return all(c.never or c.status in FINISHED for c in self.cells)

    def cell(self, column: str) -> Cell:
        return next(c for c in self.cells if c.column == column)


def row_for(filing: VatFiling, never: set[str] | None = None) -> Row:
    if never is None:
        never = set(VatNever.objects.filter(client=filing.client).values_list("column", flat=True))
    stored = {c.column: c for c in filing.cells.all()}
    cells = []
    for column in Column:
        cell = stored.get(column.value)
        status = cell.status if cell else Status.TODO
        cells.append(
            Cell(
                column=column.value,
                header=COLUMN_HEADERS[column],
                label=column.label,
                status=status,
                status_label=Status(status).label,
                on=cell.on if cell else None,
                by=cell.by if cell else None,
                comment=cell.comment if cell else "",
                never=column.value in never,
            )
        )
    return Row(filing, cells)


def grid(client: Client, today: date | None = None) -> list[Row]:
    today = today or timezone.localdate()
    ensure_filings(client, today)
    never = set(VatNever.objects.filter(client=client).values_list("column", flat=True))
    filings = (
        client.vat_filings.filter(period_start__lte=today)
        .select_related("manager", "assistant", "xml", "pdf", "ic_xml", "ic_pdf", "task")
        .prefetch_related("cells__by", "messages")
    )
    return [row_for(f, never) for f in filings]


def add_my_time(user: User, filings: list[VatFiling]) -> None:
    """Mon temps sur chaque déclaration (entrées ajoutées par « + Temps », D-110), jamais celui
    des collègues (D-107) : `filing.my_time` (« 1 h 30 »)."""
    from apps.timesheet.models import TimeEntry, hours_label, minutes_between

    totals: dict[int, int] = {}
    entries = TimeEntry.objects.filter(user=user, vat_filing__in=filings).values_list(
        "vat_filing_id", "start", "end"
    )
    for filing_id, start, end in entries:
        totals[filing_id] = totals.get(filing_id, 0) + minutes_between(start, end)
    for filing in filings:
        filing.my_time = hours_label(totals.get(filing.pk, 0))  # type: ignore[attr-defined]


# --- Modifier une case ------------------------------------------------------------------------


def set_status(
    filing: VatFiling,
    column: str,
    status: str,
    *,
    user: User | None = None,
    on: date | None = None,
    comment: str | None = None,
) -> None:
    """Change l'état d'une case. « Jamais nécessaire » vaut pour toute la colonne du client."""
    if column not in Column.values or status not in Status.values:
        raise ValueError("Case ou état inconnu.")
    with transaction.atomic():
        if status == Status.NEVER:
            VatNever.objects.get_or_create(client=filing.client, column=column)
        else:
            VatNever.objects.filter(client=filing.client, column=column).delete()
            cell, _ = VatCell.objects.get_or_create(filing=filing, column=column)
            cell.status = status
            cell.on = None if status == Status.TODO else (on or timezone.localdate())
            cell.by = None if status == Status.TODO else user
            if comment is not None:
                cell.comment = comment.strip()[:300]
            cell.save()
        sync_task(filing, user)
    events.emit(
        "vat.cell_changed",
        subject=filing.client,
        actor=user,
        payload={"periode": filing.period_key, "case": column, "etat": status},
    )


def set_comment(filing: VatFiling, column: str, comment: str) -> None:
    if column not in Column.values:
        raise ValueError("Case inconnue.")
    cell, _ = VatCell.objects.get_or_create(filing=filing, column=column)
    cell.comment = comment.strip()[:300]
    cell.save(update_fields=["comment"])


def sync_task(filing: VatFiling, user: User | None = None) -> None:
    """L'échéance suit la grille : déclaration déposée → échéance terminée."""
    task = filing.task
    if task is None:
        return
    statuses = dict(filing.cells.values_list("column", "status"))
    filed = statuses.get(Column.FILED) == Status.DONE
    started = any(s not in (Status.TODO,) for s in statuses.values())
    if filed and task.status != Task.Status.DONE:
        task.status = Task.Status.DONE
        task.completed_at, task.completed_by = timezone.now(), user
    elif not filed and task.status == Task.Status.DONE:
        task.status = Task.Status.IN_PROGRESS
        task.completed_at, task.completed_by = None, None
    elif not filed and started and task.status == Task.Status.TODO:
        task.status = Task.Status.IN_PROGRESS
    else:
        return
    task.save(update_fields=["status", "completed_at", "completed_by", "updated_at"])
