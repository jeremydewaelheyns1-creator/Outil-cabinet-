"""Lecture des règles d'échéances (`config/taches/regles.yaml`) et calcul des dates."""

from __future__ import annotations

import calendar
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from django.conf import settings

from apps.clients.models import Client

from .holidays import next_business_day
from .models import Task

RULES_FILE = Path(settings.BASE_DIR) / "config" / "taches" / "regles.yaml"

MONTHS_FR = (
    "", "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
    "septembre", "octobre", "novembre", "décembre",
)  # fmt: skip
PERIODICITIES = {"mensuelle", "trimestrielle", "annuelle", "exercice"}
DUE_TYPES = {"jour_du_mois_suivant", "mois_apres_fin", "date_annee_suivante", "dates_par_annee"}
CONDITION_FIELDS = {
    "type": "kind",
    "statut_tva": "vat_status",
    "periodicite_tva": "vat_periodicity",
}


class RuleError(ValueError):
    """Fichier de règles incohérent : refusé au chargement plutôt que mal appliqué."""


@dataclass(frozen=True)
class Period:
    key: str
    label: str
    start: date
    end: date


@dataclass(frozen=True)
class Rule:
    code: str
    title: str
    category: str
    periodicity: str
    conditions: dict[str, Any]
    due: dict[str, Any]
    business_day: bool = False
    # Fin d'une tolérance de report (ex. TVA trimestrielle : plus de report après le 30/09/2025).
    business_day_until: date | None = None
    assignee_role: str = ""
    steps: tuple[str, ...] = field(default_factory=tuple)

    # --- Le client est-il concerné ? -----------------------------------------------------

    def applies_to(self, client: Client) -> bool:
        if client.status != Client.Status.ACTIVE or client.deleted_at is not None:
            return False
        for name, allowed in self.conditions.items():
            if name == "cloture_connue":
                if bool(allowed) != bool(client.fiscal_year_end_month):
                    return False
            elif getattr(client, CONDITION_FIELDS[name]) not in allowed:
                return False
        return True

    # --- Périodes et dates ------------------------------------------------------------------

    def periods(self, client: Client, first_year: int, last_year: int) -> Iterator[Period]:
        for year in range(first_year, last_year + 1):
            if self.periodicity == "mensuelle":
                for month in range(1, 13):
                    yield Period(
                        f"{year}-{month:02d}",
                        f"{MONTHS_FR[month]} {year}",
                        date(year, month, 1),
                        _month_end(year, month),
                    )
            elif self.periodicity == "trimestrielle":
                for quarter in range(1, 5):
                    first_month = 3 * quarter - 2
                    label = "1er" if quarter == 1 else f"{quarter}e"
                    yield Period(
                        f"{year}-T{quarter}",
                        f"{label} trimestre {year}",
                        date(year, first_month, 1),
                        _month_end(year, first_month + 2),
                    )
            elif self.periodicity == "annuelle":
                yield Period(str(year), str(year), date(year, 1, 1), date(year, 12, 31))
            elif self.periodicity == "exercice" and client.fiscal_year_end_month:
                end = _closing_date(client, year)
                start = _add_months(end, -12) + timedelta(days=1)
                yield Period(
                    f"EX-{end.isoformat()}",
                    f"exercice clôturé le {end:%d/%m/%Y}",
                    start,
                    end,
                )

    def due_date(self, period: Period) -> date | None:
        kind = self.due["type"]
        if kind == "jour_du_mois_suivant":
            target = _add_months(period.end.replace(day=1), int(self.due["mois_apres"]))
            due = _day_in_month(target.year, target.month, self.due["jour"])
        elif kind == "mois_apres_fin":
            target = _add_months(period.end.replace(day=1), int(self.due["mois"]))
            due = _day_in_month(target.year, target.month, self.due["jour"])
        elif kind == "date_annee_suivante":
            due = _day_in_month(period.end.year + 1, int(self.due["mois"]), self.due["jour"])
        else:  # dates_par_annee
            value = (self.due.get("dates") or {}).get(period.end.year)
            if value is None:
                return None
            due = value if isinstance(value, date) else date.fromisoformat(str(value))
        if self.business_day and (
            self.business_day_until is None or due <= self.business_day_until
        ):
            return next_business_day(due)
        return due

    def render_title(self, period: Period) -> str:
        return self.title.replace("{periode}", period.label)[:200]


# --- Outils de dates --------------------------------------------------------------------------


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def _day_in_month(year: int, month: int, day: int | str) -> date:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, last if day == "dernier" else min(int(day), last))


def _closing_date(client: Client, year: int) -> date:
    month = client.fiscal_year_end_month or 12
    return _day_in_month(year, month, client.fiscal_year_end_day or "dernier")


# --- Chargement ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleSet:
    rules: tuple[Rule, ...]
    days_back: int
    months_ahead: int

    def get(self, code: str) -> Rule | None:
        return next((r for r in self.rules if r.code == code), None)


def _parse_rule(raw: dict[str, Any]) -> Rule:
    code = str(raw.get("code", "")).strip()
    if not code or code == "manual":
        raise RuleError(f"Règle sans code valide : {raw!r}")
    periodicity = raw.get("periodicite")
    if periodicity not in PERIODICITIES:
        raise RuleError(f"{code} : périodicité inconnue « {periodicity} ».")
    category = raw.get("categorie", Task.Category.OTHER)
    if category not in Task.Category.values:
        raise RuleError(f"{code} : catégorie inconnue « {category} ».")
    due = raw.get("echeance") or {}
    if due.get("type") not in DUE_TYPES:
        raise RuleError(f"{code} : type d'échéance inconnu « {due.get('type')} ».")
    conditions = raw.get("conditions") or {}
    for name in conditions:
        if name not in CONDITION_FIELDS and name != "cloture_connue":
            raise RuleError(f"{code} : condition inconnue « {name} ».")
    return Rule(
        code=code,
        title=str(raw.get("titre") or code),
        category=category,
        periodicity=periodicity,
        conditions=conditions,
        due=due,
        business_day=bool(raw.get("report_jour_ouvrable", False)),
        business_day_until=_until(raw.get("report_jusqu_au")),
        assignee_role=str(raw.get("responsable", "")),
        steps=tuple(str(s) for s in raw.get("etapes") or ()),
    )


def _until(value: Any) -> date | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def rules_hash(path: Path = RULES_FILE) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


@cache
def load_rules(path: Path = RULES_FILE) -> RuleSet:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules = tuple(_parse_rule(raw) for raw in data.get("regles") or [])
    codes = [r.code for r in rules]
    duplicates = {c for c in codes if codes.count(c) > 1}
    if duplicates:
        raise RuleError(f"Codes de règle en double : {', '.join(sorted(duplicates))}.")
    window = data.get("fenetre") or {}
    return RuleSet(
        rules=rules,
        days_back=int(window.get("jours_passes", 60)),
        months_ahead=int(window.get("mois_futurs", 12)),
    )
