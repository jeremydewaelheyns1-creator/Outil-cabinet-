"""Calculs de la feuille de temps : semaine en calendrier, totaux."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import cast

from apps.core.models import User

from .models import TimeEntry, hours_label

FIRST_HOUR = 7
LAST_HOUR = 20
HOUR_HEIGHT = 60  # pixels par heure dans le calendrier
SHORT_BLOCK = 44  # en dessous (moins de ~45 min) : le créneau s'affiche sur une seule ligne
DAY_NAMES = ("Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim")


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def parse_week(value: str, today: date) -> date:
    try:
        return monday_of(date.fromisoformat(value))
    except ValueError:
        return monday_of(today)


@dataclass
class Block:
    entry: TimeEntry
    top: int
    height: int
    label: str

    @property
    def is_short(self) -> bool:
        return self.height < SHORT_BLOCK


@dataclass
class Day:
    day: date
    name: str
    blocks: list[Block] = field(default_factory=list)
    minutes: int = 0
    is_today: bool = False
    is_weekend: bool = False

    @property
    def total(self) -> str:
        return hours_label(self.minutes)


def _position(entry: TimeEntry) -> tuple[int, int]:
    start = max(entry.start.hour * 60 + entry.start.minute, FIRST_HOUR * 60)
    end = min(entry.end.hour * 60 + entry.end.minute, LAST_HOUR * 60)
    top = (start - FIRST_HOUR * 60) * HOUR_HEIGHT // 60
    height = max((end - start) * HOUR_HEIGHT // 60, 22)
    return top, height


def week(user: User, monday: date, today: date) -> dict[str, object]:
    entries = list(
        TimeEntry.objects.filter(user=user, day__gte=monday, day__lt=monday + timedelta(days=7))
        .select_related("client")
        .order_by("day", "start")
    )
    days = [
        Day(monday + timedelta(days=i), DAY_NAMES[i], is_today=monday + timedelta(days=i) == today,
            is_weekend=i >= 5)
        for i in range(7)
    ]  # fmt: skip
    by_client: dict[str, int] = defaultdict(int)
    billable = 0
    for entry in entries:
        target = days[(entry.day - monday).days]
        top, height = _position(entry)
        label = entry.client.display_name if entry.client else entry.get_activity_display()
        target.blocks.append(Block(entry, top, height, label))
        target.minutes += entry.minutes
        by_client[entry.client.display_name if entry.client else "Sans dossier"] += entry.minutes
        billable += entry.minutes if entry.billable else 0
    total = sum(d.minutes for d in days)
    return {
        "days": days,
        "hours": list(range(FIRST_HOUR, LAST_HOUR)),
        "grid_height": (LAST_HOUR - FIRST_HOUR) * HOUR_HEIGHT,
        "hour_height": HOUR_HEIGHT,
        "total": hours_label(total),
        "billable": hours_label(billable),
        "billable_percent": round(100 * billable / total) if total else 0,
        "by_client": sorted(
            ((name, hours_label(m), m) for name, m in by_client.items()), key=lambda r: -r[2]
        ),
        "previous": monday - timedelta(days=7),
        "next": monday + timedelta(days=7),
        "monday": monday,
        "sunday": monday + timedelta(days=6),
    }


def minutes_on(user: User, day: date) -> int:
    return sum(e.minutes for e in TimeEntry.objects.filter(user=user, day=day))


def day_view(user: User, day: date, today: date) -> dict[str, object]:
    """Une journée en agenda (sous-onglet « Mon agenda » de Ma journée) + la semaine en bref."""
    monday = monday_of(day)
    data = week(user, monday, today)
    days = cast("list[Day]", data["days"])
    current = days[(day - monday).days]
    return {
        **data,
        "current": current,
        "day": day,
        "previous_day": day - timedelta(days=1),
        "next_day": day + timedelta(days=1),
        "is_today": day == today,
    }


def deadlines_of(user: User, day: date) -> dict[str, object]:
    """Échéances du jour (D-061) : celles à une heure dans le calendrier (pointillé), les
    autres en haut (« toute la journée »)."""
    from apps.tasks.models import Task

    tasks = list(
        Task.objects.visible_to(user).open().filter(assignee=user, due_date=day)
        .select_related("client").order_by("due_time", "title")
    )  # fmt: skip
    timed = []
    for task in tasks:
        if task.due_time is None:
            continue
        start = max(task.due_time.hour * 60 + task.due_time.minute, FIRST_HOUR * 60)
        end_time = task.end_time
        end = end_time.hour * 60 + end_time.minute if end_time else start + 30
        end = min(end, LAST_HOUR * 60)
        top = (start - FIRST_HOUR * 60) * HOUR_HEIGHT // 60
        height = max((end - start) * HOUR_HEIGHT // 60, 26)
        timed.append({"task": task, "top": top, "height": height, "short": height < SHORT_BLOCK})
    return {"timed_deadlines": timed, "allday_deadlines": [t for t in tasks if t.due_time is None]}


def reminders_today(user: User, today: date) -> list[object]:
    from apps.tasks.models import Task

    return list(
        Task.objects.visible_to(user).open()
        .filter(assignee=user, due_date=today, remind=True)
        .select_related("client").order_by("due_time")
    )  # fmt: skip
