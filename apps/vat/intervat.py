"""Lecture des fichiers déposés sur Intervat (D-040).

Le **XML** est lu de façon sûre et certaine, sans IA : il contient le numéro de TVA du
déclarant, la période et le montant de chaque grille. Deux sortes de fichiers :
- déclaration périodique (`VATConsignment` → `VATDeclaration`) ;
- listing intracommunautaire (`IntraConsignment` → `IntraListing`).

Le **PDF** n'a pas de structure garantie : on en extrait le texte (poppler, sur le serveur) et
on y cherche le numéro d'entreprise, la sorte de document et la période. Le résultat n'est
qu'une proposition, sauf s'il confirme un XML du même envoi.

Sécurité : `defusedxml` refuse les pièges connus des fichiers XML (entités externes, bombes
d'expansion) ; rien ne quitte le serveur.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException
from stdnum.be import vat as be_vat

VAT = "vat"  # déclaration périodique
IC = "ic"  # listing intracommunautaire
KIND_LABELS = {VAT: "déclaration TVA", IC: "listing intracommunautaire"}


class IntervatError(ValueError):
    """Fichier illisible ou qui n'est pas un fichier Intervat reconnu."""


@dataclass(frozen=True)
class Declaration:
    kind: str
    enterprise_number: str  # 10 chiffres
    year: int
    month: int | None = None
    quarter: int | None = None
    grids: dict[str, Decimal] = field(default_factory=dict)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(element: Element, name: str) -> list[Element]:
    return [e for e in element.iter() if _local(e.tag) == name]


def _first_text(element: Element, name: str) -> str:
    found = _children(element, name)
    return (found[0].text or "").strip() if found else ""


def normalize_number(value: str) -> str:
    """'BE0477.472.701' / '477472701' → '0477472701' (vide si ce n'est pas un numéro)."""
    digits = re.sub(r"\D", "", value)
    if len(digits) == 9:
        digits = "0" + digits
    return digits if len(digits) == 10 and be_vat.is_valid(digits) else ""


def _period(element: Element) -> tuple[int, int | None, int | None]:
    periods = _children(element, "Period")
    if not periods:
        raise IntervatError("Période absente du fichier.")
    node = periods[0]
    year_text, month_text = _first_text(node, "Year"), _first_text(node, "Month")
    quarter_text = _first_text(node, "Quarter")
    if year_text:
        year = int(year_text)
        if quarter_text:
            return year, None, int(quarter_text)
        if month_text:
            return year, int(month_text), None
        raise IntervatError("Période incomplète.")
    # Forme compacte des listings : MMAAAA (mois), 3TAAAA (trimestre).
    text = (node.text or "").strip()
    if re.fullmatch(r"3[1-4]\d{4}", text):
        return int(text[2:]), None, int(text[1])
    if re.fullmatch(r"(0[1-9]|1[0-2])\d{4}", text):
        return int(text[2:]), int(text[:2]), None
    raise IntervatError("Période illisible.")


def _amount(text: str) -> Decimal:
    try:
        return Decimal(text.replace(",", ".")).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise IntervatError("Montant illisible.") from exc


def parse_xml(content: bytes) -> list[Declaration]:
    """Toutes les déclarations du fichier (un fichier peut en grouper plusieurs)."""
    try:
        root = SafeET.fromstring(content)
    except (SafeET.ParseError, DefusedXmlException, ValueError) as exc:
        raise IntervatError("Fichier XML illisible ou refusé.") from exc
    root_name = _local(root.tag)
    if root_name == "VATConsignment":
        kind, item = VAT, "VATDeclaration"
    elif root_name == "IntraConsignment":
        kind, item = IC, "IntraListing"
    else:
        raise IntervatError("Ce n'est pas une déclaration ni un listing Intervat.")
    declarations = []
    for node in _children(root, item):
        declarants = _children(node, "Declarant")
        number = normalize_number(_first_text(declarants[0], "VATNumber")) if declarants else ""
        if not number:
            raise IntervatError("Numéro de TVA du déclarant absent ou invalide.")
        year, month, quarter = _period(node)
        if (quarter is not None and not 1 <= quarter <= 4) or (
            month is not None and not 1 <= month <= 12
        ):
            raise IntervatError("Période invalide.")
        grids = {}
        if kind == VAT:
            for amount in _children(node, "Amount"):
                grid = (amount.get("GridNumber") or "").strip()
                if grid:
                    grids[grid] = _amount((amount.text or "").strip())
        declarations.append(Declaration(kind, number, year, month, quarter, grids))
    if not declarations:
        raise IntervatError("Aucune déclaration dans le fichier.")
    return declarations


# --- PDF --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PdfClues:
    kind: str
    numbers: tuple[str, ...]  # numéros d'entreprise trouvés dans le texte
    year: int | None = None
    month: int | None = None
    quarter: int | None = None


NUMBER = re.compile(r"(?<!\d)([01]\d{3}[.\s]?\d{3}[.\s]?\d{3})(?!\d)")
QUARTER = (
    re.compile(r"\b([1-4])\s*(?:er|e|ème|de|ste)?\s*(?:trimestre|kwartaal)\s*(20\d{2})", re.I),
    re.compile(
        r"(?:trimestre|kwartaal)\s*:?\s*([1-4])\s*[-/ ]?\s*(?:ann[ée]e\s*:?\s*)?(20\d{2})", re.I
    ),
    re.compile(r"\bT([1-4])\s*[-/ ]?\s*(20\d{2})\b"),
)  # fmt: skip
MONTH = (
    re.compile(r"(?:mois|maand)\s*:?\s*(0?[1-9]|1[0-2])\s*[-/ ]\s*(20\d{2})", re.I),
)  # fmt: skip


def pdf_text(content: bytes) -> str:
    """Texte des trois premières pages (pdftotext, sur le serveur)."""
    try:
        result = subprocess.run(  # commande fixe : rien ne vient du fichier
            ["pdftotext", "-l", "3", "-layout", "-", "-"],  # noqa: S607
            input=content,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.decode("utf-8", errors="replace") if result.returncode == 0 else ""


def read_pdf(content: bytes) -> PdfClues:
    text = pdf_text(content)
    lowered = text.lower()
    kind = IC if "intracommunautaire" in lowered or "intracommunautair" in lowered else VAT
    numbers = tuple(
        dict.fromkeys(n for n in (normalize_number(m) for m in NUMBER.findall(text)) if n)
    )
    for pattern in QUARTER:
        found = {(int(m[1]), int(m[0])) for m in pattern.findall(text)}
        if len(found) == 1:
            year, quarter = found.pop()
            return PdfClues(kind, numbers, year=year, quarter=quarter)
    for pattern in MONTH:
        found = {(int(m[1]), int(m[0])) for m in pattern.findall(text)}
        if len(found) == 1:
            year, month = found.pop()
            return PdfClues(kind, numbers, year=year, month=month)
    return PdfClues(kind, numbers)
