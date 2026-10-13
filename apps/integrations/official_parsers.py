"""Lecture des pages des sites officiels (BCE publique, Moniteur belge).

Ces sites n'ont pas d'API ouverte : on lit leur page HTML. Les analyseurs sont volontairement
tolérants (ils cherchent des repères stables : intitulé « Fonctions », liens vers les PDF du
Moniteur, dates « Depuis le … ») pour survivre à un changement de mise en page. S'ils ne
trouvent rien d'exploitable, ils le disent (`None`) au lieu d'inventer.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

MONTHS = {
    "janvier": 1,
    "février": 2,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
    "decembre": 12,
}
ENTERPRISE = re.compile(r"\b([01])\s?(\d{3})[.\s]?(\d{3})[.\s]?(\d{3})\b")
SINCE = re.compile(r"depuis le\s+(\d{1,2})(?:er)?\s+([a-zéèûô]+)\s+(\d{4})", re.IGNORECASE)


def normalize(text: str) -> str:
    """Minuscules, sans accents ni ponctuation : pour comparer des noms."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _clean(text: str) -> str:
    return " ".join(unescape(text).replace("\xa0", " ").split())


# --- BCE publique : fonctions ----------------------------------------------------------------


class _Rows(HTMLParser):
    """Transforme une page en suite d'intitulés (h1–h3) et de lignes de tableau."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, list[str]]] = []
        self._rows: list[list[str]] = []
        self._cells: list[list[str]] = []
        self._heading: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._rows.append([])
        elif tag in ("td", "th"):
            self._cells.append([])
        elif tag in ("h1", "h2", "h3"):
            self._heading = []
        elif tag == "br" and self._cells:
            self._cells[-1].append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cells:
            text = _clean("".join(self._cells.pop()))
            if self._rows:
                self._rows[-1].append(text)
        elif tag == "tr" and self._rows:
            cells = self._rows.pop()
            if any(cells):
                self.events.append(("row", cells))
        elif tag in ("h1", "h2", "h3") and self._heading is not None:
            self.events.append(("heading", [_clean("".join(self._heading))]))
            self._heading = None

    def handle_data(self, data: str) -> None:
        if self._heading is not None:
            self._heading.append(data)
        elif self._cells:
            self._cells[-1].append(data)


@dataclass(frozen=True)
class Function:
    """Une fonction publiée à la BCE (administrateur, gérant…)."""

    role: str
    name: str
    first_name: str = ""
    enterprise_number: str = ""
    since: str = ""  # date ISO

    @property
    def display_name(self) -> str:
        return f"{self.name} {self.first_name}".strip()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _since(text: str) -> str:
    match = SINCE.search(text)
    if not match:
        return ""
    month = MONTHS.get(match.group(2).lower())
    if not month:
        return ""
    try:
        return date(int(match.group(3)), month, int(match.group(1))).isoformat()
    except ValueError:
        return ""


def _function_from_cells(cells: list[str]) -> Function | None:
    cells = [c for c in cells if c]
    if len(cells) < 2:
        return None
    role, rest = cells[0], " ".join(cells[1:])
    if role.lower().startswith(("depuis", "pas de")) or len(role) > 80:
        return None
    since = _since(rest)
    rest = SINCE.sub("", rest)
    number = ""
    if match := ENTERPRISE.search(rest):
        number = "".join(match.groups())
        rest = ENTERPRISE.sub("", rest)
    rest = re.sub(r"\(?\s*représentée? par.*$", "", rest, flags=re.IGNORECASE)
    rest = " ".join(rest.replace("|", " ").split()).strip(" ,-")
    if "," in rest and not number:
        last, first = (p.strip() for p in rest.split(",", 1))
    else:
        last, first = rest, ""
    if not last:
        return None
    return Function(role.rstrip(" :"), last, first, number, since)


SECTION_END = re.compile(
    r"^(capacit|qualit|autorisation|activit|caract|liens|liste des|données financ|nace|"
    r"unités d'établissement|liens externes)",
    re.IGNORECASE,
)


def parse_kbo_functions(html: str) -> list[Function] | None:
    """Fonctions d'une page entreprise de la BCE publique ; `None` si la page est illisible."""
    parser = _Rows()
    parser.feed(html)
    found_section = False
    inside = False
    functions: list[Function] = []
    for kind, values in parser.events:
        label = values[0] if values else ""
        is_title = kind == "heading" or (kind == "row" and len([v for v in values if v]) == 1)
        if is_title and normalize(label).startswith("fonctions"):
            found_section = inside = True
            continue
        if inside and is_title and (kind == "heading" or SECTION_END.match(label)):
            inside = False
            continue
        if inside and kind == "row" and (function := _function_from_cells(values)):
            functions.append(function)
    if not found_section:
        # Page sans le bloc « Fonctions » : ce n'est pas une fiche entreprise lisible.
        return None
    unique = {(f.role, normalize(f.display_name), f.enterprise_number): f for f in functions}
    return list(unique.values())


# --- Moniteur belge : publications -----------------------------------------------------------

PDF_LINK = re.compile(
    r"""href=["']([^"']*tsv_pdf/(\d{4})/(\d{2})/(\d{2})/(\d+)\.pdf)["']""", re.IGNORECASE
)
PUBLICATION_REF = re.compile(r"(\d{4}-\d{2}-\d{2})\s*/\s*(\d{5,8})")
BLOCK_BREAK = re.compile(r"<\s*(br|/p|/div|/td|/tr|/li|/h\d)\b[^>]*>", re.IGNORECASE)
TAG = re.compile(r"<[^>]+>")
SUBJECTS = (
    ("constitution", "Constitution"),
    ("statuts", "Statuts"),
    ("demission", "Démission"),
    ("nomination", "Nomination"),
    ("siege", "Siège"),
    ("capital", "Capital"),
    ("dissolution", "Dissolution"),
    ("liquidation", "Liquidation"),
    ("fusion", "Fusion"),
    ("scission", "Scission"),
    ("denomination", "Dénomination"),
    ("forme", "Forme juridique"),
    ("assemblee", "Assemblée générale"),
    ("faillite", "Faillite"),
    ("radiation", "Radiation"),
)


@dataclass(frozen=True)
class Publication:
    """Une publication d'une société aux annexes du Moniteur belge."""

    published_on: str  # date ISO
    number: str
    subject: str
    tags: tuple[str, ...]
    pdf_url: str

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tags"] = list(self.tags)
        return data


def _lines(fragment: str) -> list[str]:
    text = BLOCK_BREAK.sub("\n", fragment)
    text = TAG.sub(" ", text)
    return [line for line in (_clean(x) for x in text.split("\n")) if line]


def _subject(lines: list[str], ref_index: int | None) -> str:
    """Objet de la publication : la ligne juste avant la référence « date / numéro »."""
    candidates = lines[:ref_index] if ref_index is not None else lines
    for line in reversed(candidates):
        lowered = normalize(line)
        if not lowered or lowered in {"image", "pdf", "voir l image"} or ENTERPRISE.search(line):
            continue
        if re.fullmatch(r"[\d\s./-]+", line):
            continue
        return line[:200]
    return ""


def parse_moniteur(html: str, base_url: str) -> list[Publication] | None:
    """Publications listées sur la page du Moniteur ; `None` si la page n'en est pas une."""
    matches = list(PDF_LINK.finditer(html))
    if not matches:
        lowered = normalize(TAG.sub(" ", html))
        no_result = any(w in lowered for w in ("aucun resultat", "pas de resultat", "0 resultat"))
        return [] if no_result else None
    publications: dict[str, Publication] = {}
    previous_end = 0
    for match in matches:
        href, year, month, day, number = match.groups()
        lines = _lines(html[previous_end : match.start()])
        previous_end = match.end()
        ref_index = next((i for i, x in enumerate(lines) if PUBLICATION_REF.search(x)), None)
        if ref_index is not None and (ref := PUBLICATION_REF.search(lines[ref_index])):
            published_on, number = ref.group(1), ref.group(2)
        else:
            published_on = f"{year}-{month}-{day}"
        subject = _subject(lines, ref_index)
        normalized = normalize(subject)
        tags = tuple(label for key, label in SUBJECTS if key in normalized)
        url = urljoin(base_url, unescape(href))
        if not url.startswith(("https://", "http://")):
            continue
        publications.setdefault(url, Publication(published_on, number, subject, tags, url))
    return sorted(publications.values(), key=lambda p: p.published_on, reverse=True)
