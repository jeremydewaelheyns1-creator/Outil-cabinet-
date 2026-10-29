"""Accueil personnel (D-063) : l'écran suit la période de l'année, pour MES dossiers.

Tout part des échéances déjà calculées par l'outil (`config/taches/regles.yaml`) :

- « Mes dossiers » = ceux où je suis affecté (expert-comptable, comptable…) + les dossiers
  hybrides que j'ai pris. Jamais ceux des collègues, jamais de nom de collègue.
- Une **campagne** = mes échéances d'une même famille (TVA, listing, comptes annuels, ISOC,
  IPP, AG) qui tombent le même mois. Sa date limite = la dernière de ce mois.
- Une campagne est **en cours** de (date limite − délai d'avance de sa famille) jusqu'à la date
  limite. Grandes familles : TVA trimestrielle, listing, comptes annuels, ISOC, IPP.
- **Au centre** : la grande campagne en cours. La TVA passe toujours en premier (« en mois TVA,
  c'est LE mois TVA », mensuels compris) ; sinon la date limite la plus proche.
- **Aussi en cours** : les autres campagnes en cours qui ne sont pas terminées.
- Rien de grand en cours : **période calme** (mes dossiers à traiter dans les 30 jours, et la
  prochaine grande période).
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db.models import Q, QuerySet

from apps.clients.models import Client
from apps.core.models import User
from apps.tasks.models import Task

DONE = (Task.Status.DONE, Task.Status.NOT_APPLICABLE)
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
          "octobre", "novembre", "décembre"]  # fmt: skip
# Petit bonus en bas de l'Accueil : les sites officiels qu'on ouvre tout le temps, par groupe.
# Liens directs publiés par l'ITAA et le SPF Finances (vérifiés le 26/10/2026). Tax-on-web
# (version mandataire), Belcotax-on-web et le registre UBO s'ouvrent depuis MyMinfin : leurs
# adresses directes changent (année dans l'adresse), le lien MyMinfin, lui, reste valable.
MYMINFIN = "https://eservices.minfin.fgov.be/myminfin-web/pages/public"
LINKS = (
    ("SPF Finances", (
        ("MyMinfin", "Accès à toutes les applications", MYMINFIN),
        ("Intervat", "Déclarations et listings TVA", "https://eservices.minfin.fgov.be/InterVAT/extra/home"),
        ("Biztax", "Déclarations ISOC et INR", "https://eservices.minfin.fgov.be/BizTaxFO/home.action"),
        ("Tax-on-web", "IPP — via MyMinfin, onglet mandataire", MYMINFIN),
        ("Belcotax-on-web", "Fiches 281 — via MyMinfin", MYMINFIN),
        ("Registre UBO", "Bénéficiaires effectifs — via MyMinfin", MYMINFIN),
        ("Finprof", "Mandats et procurations du cabinet", "https://eservices.minfin.fgov.be/FINPROF2/extra/login.do"),
    )),
    ("Entreprises", (
        ("BCE publique", "Banque-Carrefour des Entreprises", "https://kbopub.economie.fgov.be/"),
        ("Centrale des bilans", "Comptes annuels (BNB)", "https://consult.cbso.nbb.be/consult-enterprise/"),
        ("Moniteur belge", "Publications des sociétés", "https://www.ejustice.just.fgov.be/cgi_tsv/list.pl"),
    )),
)  # fmt: skip
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


@dataclass(frozen=True)
class Family:
    code: str
    kinds: tuple[str, ...]
    label: str  # « Déclarations TVA »
    headline: str  # « C'est le mois TVA »
    progress: str  # « Mes déclarations TVA déposées »
    lead_days: int  # 0 : début le 1er du mois de la date limite ; sinon N jours avant
    big: bool = True
    category: str = ""  # filtre de l'échéancier
    before: str = ""  # « Pas de grande échéance avant la TVA du 20 janvier »


FAMILIES = (
    Family("tva", ("tva_trimestrielle", "tva_mensuelle"), "TVA", "C'est le mois TVA",
           "Mes déclarations TVA déposées", 0, category="tva", before="la TVA"),
    Family("listing", ("listing_clients_tva",), "Listing clients",
           "C'est le mois du listing clients", "Mes listings déposés", 0, category="tva",
           before="le listing clients"),
    Family("comptes", ("comptes_annuels",), "Comptes annuels",
           "C'est le mois des comptes annuels", "Mes comptes annuels déposés à la BNB", 0,
           category="comptes", before="les comptes annuels"),
    Family("isoc", ("isoc",), "ISOC", "C'est le mois de l'ISOC",
           "Mes déclarations ISOC déposées", 0, category="isoc", before="l'ISOC"),
    Family("ipp", ("ipp",), "IPP", "C'est la saison IPP", "Mes déclarations IPP introduites",
           165, category="ipp", before="la saison IPP"),
    Family("ag", ("assemblee_generale",), "Assemblées générales", "Assemblées générales",
           "Mes assemblées générales tenues", 0, big=False,
           category="juridique"),
)  # fmt: skip
BY_KIND = {kind: f for f in FAMILIES for kind in f.kinds}
SUB_LINES = {"tva_trimestrielle": "Trimestriels", "tva_mensuelle": "Mensuels"}
# Calendrier : préciser la TVA (mensuels le 20 avec report, trimestriels le 25 sans report, D-094).
CALENDAR_LABELS = {"tva_mensuelle": "TVA mensuelle", "tva_trimestrielle": "TVA trimestrielle"}
STATE: dict[str, tuple[str, str]] = {
    Task.Status.TODO: ("pas commencé", "gris"),
    Task.Status.IN_PROGRESS: ("en cours", "orange"),
    Task.Status.WAITING: ("en attente du client", "bleu"),
}
ORDER: dict[str, int] = {Task.Status.IN_PROGRESS: 0, Task.Status.WAITING: 1, Task.Status.TODO: 2}


def row(task: Task, today: date | None = None) -> dict[str, object]:
    """Une ligne « dossier / quoi / où on en est » ; une échéance dépassée : « en retard »."""
    label, tone = STATE.get(str(task.status), ("à faire", "gris"))
    if today is not None and task.status not in DONE and task.due_date < today:
        label, tone = "en retard", "rouge"
    return {"task": task, "state": label, "tone": tone}


@dataclass
class Campaign:
    family: Family
    deadline: date
    tasks: list[Task] = field(default_factory=list)

    @property
    def starts(self) -> date:
        if self.family.lead_days == 0:
            return self.deadline.replace(day=1)
        return self.deadline - timedelta(days=self.family.lead_days)

    @property
    def total(self) -> int:
        return sum(1 for t in self.tasks if t.status != Task.Status.NOT_APPLICABLE)

    @property
    def done(self) -> int:
        return sum(1 for t in self.tasks if t.status == Task.Status.DONE)

    @property
    def percent(self) -> int:
        return round(100 * self.done / self.total) if self.total else 100

    @property
    def finished(self) -> bool:
        return all(t.status in DONE for t in self.tasks)

    @property
    def is_big(self) -> bool:
        if self.family.code == "tva":  # « mois TVA » : seulement s'il y a des trimestriels
            return any(t.kind == "tva_trimestrielle" for t in self.tasks)
        return self.family.big

    @property
    def periods(self) -> str:
        labels = list(
            dict.fromkeys(
                t.period_label
                for t in sorted(self.tasks, key=lambda t: t.kind, reverse=True)
                if t.period_label
            )
        )
        return " et ".join(labels[:2]) + ("…" if len(labels) > 2 else "")

    @property
    def lines(self) -> list[tuple[str, int, int]]:
        """Détail sous la barre (ex. trimestriels / mensuels), seulement s'il y a 2 sortes."""
        groups: dict[str, list[Task]] = defaultdict(list)
        for task in self.tasks:
            if task.status != Task.Status.NOT_APPLICABLE:
                groups[SUB_LINES.get(task.kind, "")].append(task)
        if len(groups) < 2:
            return []
        result = []
        for name, group in sorted(groups.items()):
            period = next((t.period_label for t in group if t.period_label), "")
            done = sum(1 for t in group if t.status == Task.Status.DONE)
            result.append((f"{name} · {period}".strip(" ·"), done, len(group)))
        return result

    today: date | None = None

    @property
    def remaining(self) -> list[dict[str, object]]:
        open_tasks = [t for t in self.tasks if t.status not in DONE]
        open_tasks.sort(key=lambda t: (ORDER.get(str(t.status), 3), t.due_date, t.client.name))
        return [row(t, self.today) for t in open_tasks]


def my_clients(user: User) -> QuerySet[Client]:
    """Mes dossiers : où je suis affecté, plus les dossiers hybrides que j'ai pris."""
    from apps.clients import hybrid

    visible = Client.objects.visible_to(user).active()
    mine = Q(assignments__user=user)
    if hybrid.enabled():
        mine |= Q(accountant_hybrid=True, hybrid_claim__user=user)
    return visible.filter(mine).distinct()


def campaigns(tasks: list[Task]) -> list[Campaign]:
    grouped: dict[tuple[str, int, int], Campaign] = {}
    for task in tasks:
        family = BY_KIND.get(task.kind)
        if family is None:
            continue
        key = (family.code, task.due_date.year, task.due_date.month)
        campaign = grouped.setdefault(key, Campaign(family, task.due_date))
        campaign.tasks.append(task)
        campaign.deadline = max(campaign.deadline, task.due_date)
    return sorted(grouped.values(), key=lambda c: c.deadline)


def _days_label(days: int) -> str:
    return "aujourd'hui" if days == 0 else "demain" if days == 1 else f"{days} jours"


def long_date(day: date) -> str:
    return f"{DAYS[day.weekday()]} {day.day}{'er' if day.day == 1 else ''} {MONTHS[day.month - 1]}"


def legal_vat_dates(year: int, month: int) -> list[tuple[date, str]]:
    """Dates légales de la TVA tombant ce mois-ci, qu'on ait un dossier concerné ou non (D-094) :
    mensuelle le 20 (report au jour ouvrable), trimestrielle le 25 (sans report)."""
    from apps.tasks.rules import Period, load_rules

    rules = {r.code: r for r in load_rules().rules}
    previous = date(year, month, 1) - timedelta(days=1)  # la période se termine le mois d'avant
    found = []
    for code, wanted in (("tva_mensuelle", True), ("tva_trimestrielle", previous.month % 3 == 0)):
        rule = rules.get(code)
        if rule is None or not wanted:
            continue
        due = rule.due_date(Period("", "", previous.replace(day=1), previous))
        if due is not None and (due.year, due.month) == (year, month):
            found.append((due, CALENDAR_LABELS[code]))
    return found


def legal_dates(year: int, month: int) -> list[tuple[date, str]]:
    """Dates légales du mois, avec ou sans dossier concerné : TVA (D-094) et IPP (D-102). La
    date IPP des revenus de l'année d'avant, prolongation du SPF comprise ; « provisoire » tant
    que le SPF ne l'a pas publiée."""
    from apps.tasks.extensions import overrides
    from apps.tasks.rules import Period, load_rules

    found = legal_vat_dates(year, month)
    rule = load_rules().get("ipp")
    if rule is not None:
        income = year - 1
        period = Period(str(income), str(income), date(income, 1, 1), date(income, 12, 31))
        base = rule.due_date(period)
        moved = overrides().get((rule.code, period.key, base)) if base else None
        due = moved or base
        if due is not None and (due.year, due.month) == (year, month):
            provisional = rule.is_provisional(period) and moved is None
            found.append((due, f"IPP (revenus {income})"
                          + (" — date provisoire" if provisional else "")))  # fmt: skip
    return found


def _add_month(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def month_calendar(today: date, tasks: list[Task], shown: date | None = None) -> dict[str, object]:
    """Calendrier fiscal du mois `shown` (par défaut, le mois en cours) : mes dates limites, avec
    ce qui tombe ce jour-là, et les dates légales (TVA, IPP) même sans dossier concerné. Les
    flèches passent au mois d'avant ou d'après (D-104)."""
    month = (shown or today).replace(day=1)
    first_weekday, days = calendar.monthrange(month.year, month.month)
    marks: dict[int, list[str]] = defaultdict(list)
    for due, label in legal_dates(month.year, month.month):
        marks[due.day].append(label)
    for task in tasks:
        family = BY_KIND.get(task.kind)  # seulement les échéances fiscales (pas les rappels perso)
        if family and task.due_date.year == month.year and task.due_date.month == month.month:
            label = CALENDAR_LABELS.get(task.kind, family.label)
            if task.kind == "ipp" and any(m.startswith("IPP") for m in marks[task.due_date.day]):
                continue
            if label not in marks[task.due_date.day]:
                marks[task.due_date.day].append(label)
    cells: list[dict[str, object]] = [{"day": 0} for _ in range(first_weekday)]
    current = (month.year, month.month) == (today.year, today.month)
    cells += [{"day": d, "mark": d in marks, "today": current and d == today.day}
              for d in range(1, days + 1)]  # fmt: skip
    legend = [(d, " · ".join(labels[:3])) for d, labels in sorted(marks.items())]
    return {
        "name": f"{MONTHS[month.month - 1]} {month.year}",
        "cells": cells,
        "legend": legend,
        "current": current,
        "previous": f"{_add_month(month, -1):%Y-%m}",
        "next": f"{_add_month(month, 1):%Y-%m}",
    }


def calendar_for(user: User, today: date, shown: date) -> dict[str, object]:
    """Le calendrier d'un autre mois : mes échéances de ce mois-là."""
    month = shown.replace(day=1)
    tasks = list(
        Task.objects.filter(
            client__in=my_clients(user), due_date__gte=month, due_date__lt=_add_month(month, 1)
        )
    )
    return month_calendar(today, tasks, month)


def parse_month(value: str) -> date | None:
    """« 2026-11 » → 1er novembre 2026 ; rien ou invalide → None."""
    try:
        year, month = (int(part) for part in value.split("-"))
        return date(year, month, 1) if 2000 <= year <= 2100 else None
    except (ValueError, TypeError):
        return None


def build(user: User, today: date) -> dict[str, object]:
    from apps.clients import hybrid

    clients = my_clients(user)
    horizon = today + timedelta(days=200)
    tasks = list(
        Task.objects.filter(
            client__in=clients, due_date__gte=today - timedelta(days=40), due_date__lte=horizon
        )
        .select_related("client")
        .order_by("due_date")
    )
    all_campaigns = campaigns(tasks)
    for campaign in all_campaigns:
        campaign.today = today
    active = [c for c in all_campaigns if c.starts <= today <= c.deadline]
    big = [c for c in active if c.is_big and not c.finished] or [c for c in active if c.is_big]
    center = min(big, key=lambda c: (c.family.code != "tva", c.deadline)) if big else None
    also = [c for c in active if c is not center and not c.finished]
    later = [c for c in all_campaigns if c.is_big and c.deadline > today and not c.finished]
    upcoming = next((c for c in later if c is not center), None)
    context: dict[str, object] = {
        "today": today,
        "today_label": long_date(today),
        "has_clients": clients.exists(),
        "center": center,
        "also": also,
        "calendar": month_calendar(today, tasks),
        "hybrid": hybrid.board(user),
        "links": LINKS,
        # Mes échéances en retard (même définition que l'échéancier « Moi · en retard »).
        "late": Task.objects.visible_to(user)
        .open()
        .filter(assignee=user, due_date__lt=today)
        .count(),
    }
    if center is not None:
        days = (center.deadline - today).days
        context["countdown"] = _days_label(days)
        context["deadline_short"] = f"{center.deadline.day} {MONTHS[center.deadline.month - 1]}"
        context["deadline_label"] = f"{DAYS[center.deadline.weekday()]} {context['deadline_short']}"
    else:
        soon = today + timedelta(days=30)
        todo = [t for t in tasks if t.status not in DONE and t.due_date <= soon]
        context["todo"] = [row(t, today) for t in todo[:8]]
        context["todo_more"] = max(0, len(todo) - 8)
        if upcoming is not None:
            context["upcoming"] = upcoming
            context["upcoming_days"] = (upcoming.deadline - today).days
            context["upcoming_date"] = (
                f"{upcoming.deadline.day} {MONTHS[upcoming.deadline.month - 1]}"
            )
            context["upcoming_count"] = len({t.client_id for t in upcoming.tasks})
            context["upcoming_switch"] = upcoming.starts
    return context
