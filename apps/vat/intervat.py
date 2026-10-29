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
from stdnum import iban
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
    looks_like_vat: bool = False  # le texte parle bien d'une déclaration ou d'un listing TVA


VAT_TITLE = re.compile(
    r"d[ée]claration\s+p[ée]riodique|periodieke\s+(?:btw-?)?aangifte"
    r"|d[ée]claration\s+(?:[àa]\s+la\s+)?tva|btw-?aangifte|aangifte\s+(?:van\s+de\s+)?btw"
    r"|listing\s+intracommunautaire|relev[ée]\s+intracommunautaire|intracommunautaire\s+opgave"
    r"|intervat"
)
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
    # Une déclaration périodique cite souvent des grilles « intracommunautaires » (44, 46, 86…) :
    # c'est son titre qui décide, pas ce mot (trouvé lors du grand test de Jeremy).
    periodic = re.search(r"d[ée]claration\s+p[ée]riodique|periodieke\s+(?:btw-?)?aangifte", lowered)
    kind = IC if "intracommunautair" in lowered and not periodic else VAT
    # Il faut le titre d'un document TVA, pas seulement les mots « TVA » et « déclaration » :
    # une lettre de mission (« hors TVA », « déclarations à l'impôt des sociétés ») ou une
    # procuration les contiennent aussi (dossier de test 3, D-101).
    looks = bool(VAT_TITLE.search(lowered))
    numbers = tuple(
        dict.fromkeys(n for n in (normalize_number(m) for m in NUMBER.findall(text)) if n)
    )
    for pattern in QUARTER:
        found = {(int(m[1]), int(m[0])) for m in pattern.findall(text)}
        if len(found) == 1:
            year, quarter = found.pop()
            return PdfClues(kind, numbers, year=year, quarter=quarter, looks_like_vat=looks)
    for pattern in MONTH:
        found = {(int(m[1]), int(m[0])) for m in pattern.findall(text)}
        if len(found) == 1:
            year, month = found.pop()
            return PdfClues(kind, numbers, year=year, month=month, looks_like_vat=looks)
    return PdfClues(kind, numbers, looks_like_vat=looks)


_GRID_LINE = re.compile(
    r"^\s*(71|72)\b[^\n]*?(\d{1,3}(?:[ .\u00a0\u202f]\d{3})*,\d{2})\s*(?:EUR|€)?\s*$", re.M
)


def pdf_grids(text: str) -> dict[str, Decimal]:
    """Grilles 71 / 72 lues sur un PDF de déclaration (« 71 Taxe due à l'État 8 694,00 EUR »).
    Seulement si chaque grille trouvée n'a qu'une seule valeur ; sinon rien (D-092)."""
    found: dict[str, set[Decimal]] = {}
    for grid, raw in _GRID_LINE.findall(text):
        digits = re.sub(r"[ .\u00a0\u202f]", "", raw).replace(",", ".")
        found.setdefault(grid, set()).add(Decimal(digits).quantize(Decimal("0.01")))
    if any(len(values) != 1 for values in found.values()):
        return {}
    return {grid: values.pop() for grid, values in found.items()}


# --- Données de paiement lues sur le PDF (D-043) ---------------------------------------------

STRUCTURED = re.compile(
    r"(?:\+\+\+|\*\*\*)\s*(\d{3})\s*/\s*(\d{4})\s*/\s*(\d{5})\s*(?:\+\+\+|\*\*\*)"
)
IBAN = re.compile(r"\bBE\d{2}(?:\s?\d{4}){3}\b")
PAY_WORDS = ("paiement", "payer", "verser", "versement", "virement", "betaling", "betalen")
REFUND_WORDS = ("restitution", "rembours", "terugbetaling", "teruggave")


def _structured_ok(digits: str) -> bool:
    """Chiffres de contrôle d'une communication structurée belge (modulo 97)."""
    check = int(digits[:10]) % 97 or 97
    return check == int(digits[10:])


def payment_details(text: str) -> tuple[str, str]:
    """(compte, communication structurée) lus sur la déclaration, seulement s'ils sont sûrs :
    chiffres de contrôle corrects, un seul candidat, et le compte doit être sur une ligne qui
    parle de paiement (jamais le compte du client pour une restitution). Sinon : vides."""
    references = {
        f"+++{a}/{b}/{c}+++" for a, b, c in STRUCTURED.findall(text) if _structured_ok(a + b + c)
    }
    accounts = set()
    for line in text.splitlines():
        lowered = line.lower()
        if not any(w in lowered for w in PAY_WORDS) or any(w in lowered for w in REFUND_WORDS):
            continue
        for found in IBAN.findall(line):
            compact = found.replace(" ", "")
            if iban.is_valid(compact):
                accounts.add(iban.format(compact))
    account = accounts.pop() if len(accounts) == 1 else ""
    reference = references.pop() if len(references) == 1 else ""
    return account, reference


BIC = re.compile(r"BIC\s*:?\s*([A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b")
BENEFICIARY = re.compile(r"paiement\s+à\s+[\"«“]\s*([^\"»”]{2,40}?)\s*[\"»”]", re.I)


def payment_extras(text: str) -> tuple[str, str]:
    """(bénéficiaire, BIC) de la ligne de paiement, comme sur les PDF de l'administration :
    « Pour tout paiement à "TVA-BTW" - BE.. (BIC : GEBABEBB) … ». Vides si absents."""
    for line in text.splitlines():
        lowered = line.lower()
        if "paiement" not in lowered or any(w in lowered for w in REFUND_WORDS):
            continue
        beneficiary = BENEFICIARY.search(line)
        bic = BIC.search(line)
        if beneficiary or bic:  # une ligne qui cite seulement « paiement » ne suffit pas
            return (
                beneficiary.group(1).strip() if beneficiary else "",
                bic.group(1) if bic else "",
            )
    return "", ""


# --- Aperçu lisible d'un fichier XML (D-097) --------------------------------------------------

# Libellés des grilles de la déclaration périodique (formulaire du SPF Finances).
GRID_LABELS: dict[str, str] = {
    "00": "Opérations soumises à un régime particulier",
    "01": "Opérations soumises au taux de 6 %",
    "02": "Opérations soumises au taux de 12 %",
    "03": "Opérations soumises au taux de 21 %",
    "44": "Services intracommunautaires (art. 21, § 2)",
    "45": "Opérations pour lesquelles la TVA est due par le cocontractant",
    "46": "Livraisons intracommunautaires exemptées et ventes ABC",
    "47": "Autres opérations exemptées et opérations à l'étranger",
    "48": "Notes de crédit sur les opérations des grilles 44 et 46",
    "49": "Notes de crédit sur les autres opérations",
    "54": "TVA due sur les opérations des grilles 01, 02 et 03",
    "55": "TVA due sur les acquisitions intracommunautaires (grilles 86 et 88)",
    "56": "TVA due sur les opérations de la grille 87",
    "57": "TVA due sur les importations avec report de perception",
    "59": "TVA déductible",
    "61": "Régularisations en faveur de l'État",
    "62": "Régularisations en faveur du déclarant",
    "63": "TVA à reverser mentionnée sur les notes de crédit reçues",
    "64": "TVA à récupérer mentionnée sur les notes de crédit délivrées",
    "71": "Taxe due à l'État",
    "72": "Somme due par l'État",
    "81": "Marchandises, matières premières et auxiliaires",
    "82": "Services et biens divers",
    "83": "Biens d'investissement",
    "84": "Notes de crédit reçues (grilles 86 et 88)",
    "85": "Autres notes de crédit reçues",
    "86": "Acquisitions intracommunautaires et ventes ABC",
    "87": "Autres opérations à l'entrée avec TVA due par le déclarant",
    "88": "Services intracommunautaires reçus (art. 21, § 2)",
    "91": "TVA réellement due pour la période du 1er au 20 décembre",
}
GRID_SECTIONS = (
    ("Opérations à la sortie", ("00", "01", "02", "03", "44", "45", "46", "47", "48", "49")),
    ("Opérations à l'entrée", ("81", "82", "83", "84", "85", "86", "87", "88")),
    ("Taxes dues", ("54", "55", "56", "57", "61", "63")),
    ("Taxes déductibles", ("59", "62", "64")),
    ("Solde", ("71", "72", "91")),
)


@dataclass(frozen=True)
class Preview:
    kind: str
    enterprise_number: str
    period: str
    sections: list[tuple[str, list[tuple[str, str, Decimal]]]]
    clients: list[tuple[str, str, Decimal]]  # listing IC : (n° de TVA, code, montant)


def preview(content: bytes) -> Preview | None:
    """Le XML d'Intervat mis en tableau lisible (déclaration ou listing). None : pas lisible."""
    try:
        declarations = parse_xml(content)
    except IntervatError:
        return None
    first = declarations[0]
    period = (f"{first.quarter}e trimestre {first.year}" if first.quarter
              else f"{first.month:02d}/{first.year}")  # fmt: skip
    sections = []
    for title, grids in GRID_SECTIONS:
        rows = [(g, GRID_LABELS[g], first.grids[g]) for g in grids if g in first.grids]
        if rows:
            sections.append((title, rows))
    clients: list[tuple[str, str, Decimal]] = []
    if first.kind == IC:
        root = SafeET.fromstring(content)
        for node in _children(root, "IntraClient"):
            number = _first_text(node, "CompanyVATNumber")
            issued = next((e.get("issuedBy", "") for e in _children(node, "CompanyVATNumber")), "")
            amount = _first_text(node, "Amount")
            clients.append((f"{issued}{number}", _first_text(node, "Code"),
                            _amount(amount) if amount else Decimal("0.00")))  # fmt: skip
    return Preview(first.kind, first.enterprise_number, period, sections, clients)
