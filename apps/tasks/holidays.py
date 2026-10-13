"""Jours fériés légaux belges et report d'une échéance au jour ouvrable suivant."""

from datetime import date, timedelta
from functools import cache


def easter(year: int) -> date:
    """Dimanche de Pâques (calendrier grégorien, algorithme de Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


@cache
def public_holidays(year: int) -> frozenset[date]:
    sunday = easter(year)
    return frozenset(
        {
            date(year, 1, 1),  # Nouvel an
            sunday + timedelta(days=1),  # Lundi de Pâques
            date(year, 5, 1),  # Fête du travail
            sunday + timedelta(days=39),  # Ascension
            sunday + timedelta(days=50),  # Lundi de Pentecôte
            date(year, 7, 21),  # Fête nationale
            date(year, 8, 15),  # Assomption
            date(year, 11, 1),  # Toussaint
            date(year, 11, 11),  # Armistice
            date(year, 12, 25),  # Noël
        }
    )


def is_business_day(day: date) -> bool:
    return day.weekday() < 5 and day not in public_holidays(day.year)


def next_business_day(day: date) -> date:
    """Le jour même s'il est ouvrable, sinon le premier jour ouvrable suivant."""
    while not is_business_day(day):
        day += timedelta(days=1)
    return day
