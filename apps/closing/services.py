"""Clôture (D-111) : la checklist d'un dossier, ses exercices, coches et commentaires."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.clients.models import Assignment, Client
from apps.core import events
from apps.core.models import User
from apps.tasks.models import Task

from .models import (
    ClosingYear,
    Comment,
    CommonItem,
    DossierChange,
    DossierItem,
    DossierSetup,
    Kind,
    Tick,
)

VAT_STATUSES = {Client.VatStatus.SUBJECT, Client.VatStatus.MIXED}


def kind_for(client: Client) -> str:
    """Checklist commune du dossier : soumis à TVA (assujetti, mixte) ou non."""
    return Kind.VAT if client.vat_status in VAT_STATUSES else Kind.NO_VAT


# --- La liste des champs d'un dossier ---------------------------------------------------------


@dataclass(frozen=True)
class Item:
    key: str
    label: str
    hint: str
    common: bool  # vient de la checklist commune (sinon : ajouté pour ce dossier)
    changed: bool = False  # renommé pour ce dossier


def items_for(client: Client) -> list[Item]:
    """Les champs de la checklist du dossier : la checklist commune, avec ce que le dossier a
    retiré, renommé ou ajouté, dans l'ordre choisi pour le dossier."""
    changes = {c.item_id: c for c in DossierChange.objects.filter(client=client)}
    found: list[Item] = []
    for common in CommonItem.objects.filter(kind=kind_for(client), active=True):
        change = changes.get(common.pk)
        if change is not None and change.removed:
            continue
        label = (change.label if change else "") or common.label
        hint = (change.hint if change else "") or common.hint
        renamed = bool(change and (change.label or change.hint))
        found.append(Item(common.key, label, hint, True, renamed))
    for own in DossierItem.objects.filter(client=client, active=True):
        found.append(Item(own.key, own.label, own.hint, False))
    setup = DossierSetup.objects.filter(client=client).first()
    if setup is not None and setup.order:
        rank = {key: index for index, key in enumerate(setup.order)}
        natural = {item.key: index for index, item in enumerate(found)}
        found.sort(key=lambda i: (rank.get(i.key, len(rank) + natural[i.key]), natural[i.key]))
    return found


def removed_for(client: Client) -> list[CommonItem]:
    """Champs communs retirés pour ce dossier (pour pouvoir les remettre)."""
    return list(
        CommonItem.objects.filter(
            kind=kind_for(client), active=True, changes__client=client, changes__removed=True
        )
    )


def _save_order(client: Client, keys: list[str]) -> None:
    setup, _ = DossierSetup.objects.get_or_create(client=client)
    setup.order = keys
    setup.save()


def move(client: Client, key: str, step: int) -> None:
    keys = [i.key for i in items_for(client)]
    if key not in keys:
        raise ValueError("Champ inconnu.")
    index = keys.index(key)
    other = index + step
    if 0 <= other < len(keys):
        keys[index], keys[other] = keys[other], keys[index]
        _save_order(client, keys)


def rename(client: Client, key: str, label: str, hint: str) -> None:
    label, hint = label.strip()[:80], hint.strip()[:200]
    if not label:
        raise ValueError("Le nom du champ est obligatoire.")
    if key.startswith("c"):
        common = CommonItem.objects.get(pk=int(key[1:]), kind=kind_for(client))
        change, _ = DossierChange.objects.get_or_create(client=client, item=common)
        change.label = "" if label == common.label else label
        change.hint = "" if hint == common.hint else hint
        change.save()
    else:
        DossierItem.objects.filter(client=client, pk=int(key[1:])).update(label=label, hint=hint)


def remove(client: Client, key: str) -> None:
    if key.startswith("c"):
        common = CommonItem.objects.get(pk=int(key[1:]), kind=kind_for(client))
        change, _ = DossierChange.objects.get_or_create(client=client, item=common)
        change.removed = True
        change.save()
    else:
        DossierItem.objects.filter(client=client, pk=int(key[1:])).update(active=False)


def restore(client: Client, common_id: int) -> None:
    DossierChange.objects.filter(client=client, item_id=common_id).update(removed=False)


def add(client: Client, label: str, hint: str) -> DossierItem:
    label = label.strip()[:80]
    if not label:
        raise ValueError("Le nom du champ est obligatoire.")
    return DossierItem.objects.create(client=client, label=label, hint=hint.strip()[:200])


def parse_key(key: str) -> str:
    if len(key) < 2 or key[0] not in "cd" or not key[1:].isdigit():
        raise ValueError("Champ inconnu.")
    return key


# --- Les checklists communes (réglages généraux) ----------------------------------------------


def common_add(kind: str, label: str, hint: str) -> CommonItem:
    label = label.strip()[:80]
    if not label or kind not in Kind.values:
        raise ValueError("Le nom du champ est obligatoire.")
    last = CommonItem.objects.filter(kind=kind).aggregate(n=Max("position"))["n"] or 0
    return CommonItem.objects.create(
        kind=kind, label=label, hint=hint.strip()[:200], position=last + 1
    )


def common_move(item: CommonItem, step: int) -> None:
    siblings = list(CommonItem.objects.filter(kind=item.kind, active=True))
    index = next(i for i, s in enumerate(siblings) if s.pk == item.pk)
    other = index + step
    if not 0 <= other < len(siblings):
        return
    siblings[index], siblings[other] = siblings[other], siblings[index]
    with transaction.atomic():
        for position, sibling in enumerate(siblings, start=1):
            if sibling.position != position:
                sibling.position = position
                sibling.save(update_fields=["position"])


# --- Les exercices ------------------------------------------------------------------------------


def _year_end(client: Client, year: int) -> date:
    month = client.fiscal_year_end_month or 12
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(client.fiscal_year_end_day or last, last))


def _start_after(previous_end: date) -> date:
    return date.fromordinal(previous_end.toordinal() + 1)


def ensure_years(client: Client, today: date | None = None) -> None:
    """Une ligne pour le dernier exercice terminé (créée toute seule)."""
    today = today or timezone.localdate()
    if not client.fiscal_year_end_month:
        return
    end = _year_end(client, today.year)
    if end > today:
        end = _year_end(client, today.year - 1)
    if ClosingYear.objects.filter(client=client, end=end).exists():
        return
    team = {a.role: a.user for a in client.assignments.select_related("user")}
    ClosingYear.objects.create(
        client=client,
        start=_start_after(_year_end(client, end.year - 1)),
        end=end,
        manager=team.get(Assignment.Role.MANAGER),
        assistant=team.get(Assignment.Role.ASSISTANT),
    )


@dataclass
class Line:
    item: Item
    tick: Tick | None
    comments: list[Comment] = field(default_factory=list)

    @property
    def open_comments(self) -> list[Comment]:
        return [c for c in self.comments if c.is_open]

    @property
    def state(self) -> str:
        """ok / na / wip (commentaire ouvert) / todo."""
        if self.open_comments:
            return "wip"
        return self.tick.status if self.tick else "todo"


@dataclass
class Sheet:
    """La checklist d'un exercice, prête à afficher."""

    year: ClosingYear
    lines: list[Line]

    @property
    def total(self) -> int:
        return len(self.lines)

    @property
    def done(self) -> int:
        return sum(1 for line in self.lines if line.state in ("ok", "na"))

    @property
    def in_progress(self) -> list[Line]:
        return [line for line in self.lines if line.state == "wip"]

    @property
    def missing(self) -> int:
        return self.total - self.done

    @property
    def complete(self) -> bool:
        return self.total > 0 and self.done == self.total

    @property
    def percent(self) -> int:
        return round(100 * self.done / self.total) if self.total else 0

    @property
    def finished(self) -> bool:
        """La ligne de l'exercice passe au vert."""
        return self.complete and self.year.closed_on is not None


def sheet(year: ClosingYear, items: list[Item] | None = None) -> Sheet:
    items = items if items is not None else items_for(year.client)
    ticks = {t.key: t for t in year.ticks.select_related("by")}
    comments: dict[str, list[Comment]] = {}
    for comment in year.comments.select_related("author", "resolved_by"):
        comments.setdefault(comment.key, []).append(comment)
    return Sheet(year, [Line(i, ticks.get(i.key), comments.get(i.key, [])) for i in items])


def item_label(year: ClosingYear, key: str) -> str:
    found = next((i for i in items_for(year.client) if i.key == key), None)
    if found is None:
        raise ValueError("Champ inconnu pour ce dossier.")
    return found.label


def set_tick(year: ClosingYear, key: str, status: str, user: User) -> None:
    """Coche (OK, pas concerné) ou décoche une ligne. Refusé tant qu'un commentaire est ouvert."""
    label = item_label(year, key)
    if not status:
        Tick.objects.filter(year=year, key=key).delete()
        return
    if status not in Tick.Status.values:
        raise ValueError("État inconnu.")
    if year.comments.filter(key=key, resolved_at__isnull=True).exists():
        raise ValueError("Un commentaire est ouvert sur cette ligne : réglez-le d'abord.")
    Tick.objects.update_or_create(
        year=year, key=key,
        defaults={"status": status, "label": label, "on": timezone.localdate(), "by": user},
    )  # fmt: skip


def add_comment(year: ClosingYear, key: str, text: str, user: User) -> Comment:
    text = text.strip()
    if not text:
        raise ValueError("Le commentaire est vide.")
    label = item_label(year, key)
    Tick.objects.filter(year=year, key=key).delete()  # une ligne commentée n'est plus verte
    return Comment.objects.create(year=year, key=key, label=label, text=text[:2000], author=user)


def resolve(comment: Comment, user: User) -> None:
    """« Réglé » : le commentaire se ferme et la ligne est cochée."""
    comment.resolved_at, comment.resolved_by = timezone.now(), user
    comment.save(update_fields=["resolved_at", "resolved_by"])
    if not comment.year.comments.filter(key=comment.key, resolved_at__isnull=True).exists():
        Tick.objects.update_or_create(
            year=comment.year, key=comment.key,
            defaults={"status": Tick.Status.OK, "label": comment.label,
                      "on": timezone.localdate(), "by": user},
        )  # fmt: skip


def set_closed(year: ClosingYear, closed: bool, user: User) -> None:
    year.closed_on = timezone.localdate() if closed else None
    year.closed_by = user if closed else None
    year.save(update_fields=["closed_on", "closed_by"])
    events.emit(
        "closing.accounting_closed" if closed else "closing.accounting_reopened",
        subject=year.client,
        actor=user,
        payload={"exercice": year.label},
    )


def deposit(year: ClosingYear) -> str:
    task = Task.objects.filter(
        client=year.client, kind="comptes_annuels", period_key=f"EX-{year.end.isoformat()}"
    ).first()
    if task is not None and task.status == Task.Status.DONE and task.completed_at:
        return f"BNB déposé le {timezone.localtime(task.completed_at):%d/%m/%Y}"
    if task is not None:
        return f"BNB pour le {task.due_date:%d/%m/%Y}"
    month = year.end.month + 7
    target_year, target_month = year.end.year + (month - 1) // 12, (month - 1) % 12 + 1
    last = calendar.monthrange(target_year, target_month)[1]
    return f"BNB pour le {date(target_year, target_month, last):%d/%m/%Y}"


def add_my_time(user: User, years: list[ClosingYear]) -> None:
    """Mon temps sur chaque exercice (« + Temps »), jamais celui des collègues (D-107)."""
    from apps.timesheet.models import TimeEntry, hours_label, minutes_between

    totals: dict[int, int] = {}
    entries = TimeEntry.objects.filter(user=user, closing_year__in=years).values_list(
        "closing_year_id", "start", "end"
    )
    for year_id, start, end in entries:
        totals[year_id] = totals.get(year_id, 0) + minutes_between(start, end)
    for year in years:
        year.my_time = hours_label(totals.get(year.pk, 0))  # type: ignore[attr-defined]
