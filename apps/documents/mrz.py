"""Lignes « machine » (MRZ) au dos d'une carte d'identité : lecture et contrôle (D-035).

Format TD1 de l'OACI (Doc 9303, partie 5) : 3 lignes de 30 caractères. Chaque donnée
importante est suivie d'un chiffre de contrôle (pondérations 7-3-1), plus un chiffre de
contrôle global : si tous tombent juste, la lecture est vérifiée mathématiquement.

Carte belge : le numéro de carte a 12 chiffres ; les 9 premiers sont dans le champ « numéro
de document », dont le chiffre de contrôle est alors remplacé par « < », et les 3 derniers
suivis du vrai chiffre de contrôle sont au début des données facultatives de la ligne 1. Le
numéro national figure dans les données facultatives de la ligne 2.

Le numéro national lu ne sert qu'à la comparaison avec la fiche : il n'est jamais renvoyé dans
un message, un journal ou un écran.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

WEIGHTS = (7, 3, 1)
LINE = re.compile(r"^[A-Z0-9<]{30}$")


def _value(char: str) -> int:
    if char.isdigit():
        return int(char)
    if char == "<":
        return 0
    return ord(char) - 55  # A = 10 … Z = 35


def check_digit(data: str) -> str:
    return str(sum(_value(c) * WEIGHTS[i % 3] for i, c in enumerate(data)) % 10)


def _date(text: str, *, future: bool) -> date | None:
    """AAMMJJ → date. Siècle : passé pour une naissance, futur proche pour une expiration."""
    if not text.isdigit():
        return None
    year, month, day = int(text[:2]), int(text[2:4]), int(text[4:6])
    today = date.today()
    century = 2000 if (future or 2000 + year <= today.year) else 1900
    if future and 2000 + year > today.year + 30:
        century = 1900
    try:
        return date(century + year, month, day)
    except ValueError:
        return None


@dataclass
class MrzResult:
    document_code: str
    country: str
    document_number: str
    surname: str
    given_names: str
    birth_date: date | None
    expiry_date: date | None
    sex: str
    nationality: str
    national_number: str = field(repr=False)  # jamais affiché
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return bool(self.checks) and all(self.checks.values())

    @property
    def failed_checks(self) -> list[str]:
        return [name for name, ok in self.checks.items() if not ok]


def _windows(raw: str) -> list[str]:
    """Morceaux de 30 caractères possibles d'une ligne lue (l'OCR ajoute parfois un caractère
    parasite au début ou à la fin)."""
    line = re.sub(r"\s+", "", raw.upper()).replace("«", "<").replace("‹", "<")
    line = re.sub(r"[^A-Z0-9<]", "", line)
    if len(line) < 30 or len(line) > 34:
        return []
    return [line[i : i + 30] for i in range(len(line) - 29)]


def find_lines(text: str) -> list[str] | None:
    """Les trois lignes MRZ dans un texte lu (OCR). Si l'OCR a ajouté un caractère parasite,
    on essaie chaque découpage et on garde celui dont tous les contrôles tombent juste."""
    rows = [w for w in (_windows(raw) for raw in text.splitlines()) if w]
    fallback = None
    for i in range(len(rows) - 2):
        for line1 in rows[i]:
            if line1[:1] not in "IAC":
                continue
            for line2 in rows[i + 1]:
                for line3 in rows[i + 2]:
                    lines = [line1, line2, line3]
                    if parse_td1(lines).valid:
                        return lines
                    fallback = fallback or lines
    return fallback


def parse_td1(lines: list[str]) -> MrzResult:
    line1, line2, line3 = lines
    number_field, number_check = line1[5:14], line1[14]
    optional1 = line1[15:30]
    checks: dict[str, bool] = {}
    if number_check == "<":
        # Numéro long (carte belge) : suite et contrôle dans les données facultatives.
        tail = optional1.split("<", 1)[0]
        document_number = number_field + tail[:-1]
        checks["numéro de carte"] = bool(tail) and check_digit(document_number) == tail[-1]
    else:
        document_number = number_field.rstrip("<")
        checks["numéro de carte"] = check_digit(number_field) == number_check
    birth, expiry = line2[0:6], line2[8:14]
    checks["date de naissance"] = check_digit(birth) == line2[6]
    checks["date d'expiration"] = check_digit(expiry) == line2[14]
    composite = line1[5:30] + line2[0:7] + line2[8:15] + line2[18:29]
    checks["contrôle global"] = check_digit(composite) == line2[29]
    names = line3.rstrip("<").split("<<", 1)
    surname = names[0].replace("<", " ").strip()
    given = names[1].replace("<", " ").strip() if len(names) > 1 else ""
    return MrzResult(
        document_code=line1[0:2].replace("<", ""),
        country=line1[2:5],
        document_number=document_number,
        surname=surname,
        given_names=given,
        birth_date=_date(birth, future=False),
        expiry_date=_date(expiry, future=True),
        sex=line2[7],
        nationality=line2[15:18],
        national_number=line2[18:29].rstrip("<") if line2[18:29].strip("<").isdigit() else "",
        checks=checks,
    )


def read(text: str) -> MrzResult | None:
    lines = find_lines(text)
    return parse_td1(lines) if lines else None


# --- Fabrication de lignes MRZ fictives (tests et démonstration uniquement) ------------------


def build_td1(
    *,
    document_number: str,
    surname: str,
    given_names: str,
    birth: str,
    expiry: str,
    sex: str = "F",
    national_number: str = "",
    country: str = "BEL",
) -> list[str]:
    """Lignes MRZ d'une carte fictive, avec des chiffres de contrôle corrects."""
    if len(document_number) > 9:
        head, tail = document_number[:9], document_number[9:]
        line1 = f"ID{country}{head}<{tail}{check_digit(document_number)}".ljust(30, "<")
    else:
        padded = document_number.ljust(9, "<")
        line1 = f"ID{country}{padded}{check_digit(padded)}".ljust(30, "<")
    optional2 = national_number.ljust(11, "<")
    line2 = f"{birth}{check_digit(birth)}{sex}{expiry}{check_digit(expiry)}{country}{optional2}"
    composite = line1[5:30] + line2[0:7] + line2[8:15] + line2[18:29]
    line2 += check_digit(composite)
    name = f"{surname.replace(' ', '<')}<<{given_names.replace(' ', '<')}".upper()
    return [line1, line2, name.ljust(30, "<")[:30]]
