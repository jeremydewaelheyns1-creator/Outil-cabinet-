"""Fichiers XBRL officiels déposés dans « Déposer des documents » : reconnus et classés (D-098).

Deux sortes, apprises sur de vrais fichiers anonymisés que Jeremy a fournis (gardés hors du
dépôt ; les tests utilisent des copies fictives) :

- **comptes annuels** au format de la Banque Nationale (`.xbrl`, taxonomie « pfs » de la
  BNB) → rangés avec les comptes annuels du dossier ;
- **déclaration Biztax** (`.biztax` : `<biztax><xbrl>`, taxonomie du SPF Finances) → ISOC
  (ou IPM, INR selon le type de déclaration).

Le dossier est trouvé par le numéro d'entreprise du fichier (`identifier` « fgov.be »), parmi
les dossiers visibles de la personne qui dépose. L'exercice vient des dates du fichier. Pour
l'aperçu, quelques chiffres clés de l'exercice (jamais de nom ni d'adresse) et le nom des
annexes jointes à la déclaration Biztax (leur contenu n'est ni lu ni gardé à part).
Lecture sûre (defusedxml) : pas d'entité externe, pas de bombe XML.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

ACCOUNTS = "comptes"
BIZTAX = "biztax"

# Chiffres clés des comptes annuels (BNB) : (élément, libellé, contexte « instant » ou durée).
ACCOUNTS_FIGURES: tuple[tuple[str, str], ...] = (
    ("Turnover", "Chiffre d'affaires"),
    ("GrossOperatingMargin", "Marge brute d'exploitation"),
    ("OperatingProfitLoss", "Bénéfice (perte) d'exploitation"),
    ("GainLossBeforeTaxes", "Bénéfice (perte) avant impôts"),
    ("GainLossPeriod", "Bénéfice (perte) de l'exercice"),
    ("Equity", "Capitaux propres"),
    ("AmountsPayable", "Dettes"),
    ("Assets", "Total du bilan"),
)
# Chiffres clés de la déclaration Biztax.
BIZTAX_FIGURES: tuple[tuple[str, str], ...] = (
    ("FiscalResult", "Résultat fiscal"),
    ("BasicTaxableAmountCommonRateCITRN", "Base imposable au taux ordinaire"),
    ("BasicTaxableAmountReducedRateCITRN", "Base imposable au taux réduit"),
    ("Prepayments", "Versements anticipés"),
)
# Annexes jointes à une déclaration Biztax (fichiers PDF intégrés au XBRL).
BIZTAX_ANNEXES: dict[str, str] = {
    "StatutoryAccounts": "Comptes annuels",
    "InternalStatutoryAccounts": "Comptes internes",
    "GeneralMeetingMinutesDecisions": "Procès-verbal de l'assemblée générale",
    "DepreciationTableNonStructured": "Tableau des amortissements",
    "OtherDocuments": "Autres documents",
}
# Type de déclaration Biztax → impôt.
RETURN_TYPES = {
    "venb": "ISOC",
    "rpb": "IPM",
    "bni": "INR",
}
MODELS = {"abbr": "abrégé", "full": "complet", "micro": "micro"}


@dataclass
class Filing:
    kind: str  # ACCOUNTS ou BIZTAX
    enterprise_number: str  # 10 chiffres
    start: date | None
    end: date | None
    assessment_year: int | None = None  # Biztax : exercice d'imposition
    tax: str = ""  # Biztax : ISOC, IPM ou INR
    model: str = ""  # comptes : abrégé, complet, micro
    approved_on: date | None = None  # comptes : date de l'assemblée générale
    figures: list[tuple[str, Decimal]] = field(default_factory=list)
    annexes: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        if self.kind == ACCOUNTS:
            end = f" — exercice clôturé le {self.end:%d/%m/%Y}" if self.end else ""
            return f"Comptes annuels (XBRL){end}"
        year = f" — exercice d'imposition {self.assessment_year}" if self.assessment_year else ""
        return f"Déclaration {self.tax or 'ISOC'} Biztax (XBRL){year}"

    @property
    def period(self) -> str:
        if self.start and self.end:
            return f"du {self.start:%d/%m/%Y} au {self.end:%d/%m/%Y}"
        return f"clôturé le {self.end:%d/%m/%Y}" if self.end else ""


def _local(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _namespace(tag: object) -> str:
    text = str(tag)
    return text[1:].split("}", 1)[0] if text.startswith("{") else ""


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat((value or "").strip()[:10])
    except ValueError:
        return None


def _amount(value: str | None) -> Decimal | None:
    try:
        return Decimal((value or "").strip())
    except InvalidOperation:
        return None


def _contexts(xbrl: Element) -> dict[str, tuple[date | None, date | None, bool]]:
    """Contexte → (début, fin, a des dimensions). Un instant : (None, date)."""
    found: dict[str, tuple[date | None, date | None, bool]] = {}
    for context in xbrl:
        if _local(context.tag) != "context":
            continue
        dates = {_local(e.tag): _date(e.text) for e in context.iter()
                 if _local(e.tag) in ("instant", "startDate", "endDate")}  # fmt: skip
        dimensional = any(_local(e.tag) in ("explicitMember", "typedMember")
                          for e in context.iter())  # fmt: skip
        end = dates.get("endDate") or dates.get("instant")
        found[context.get("id", "")] = (dates.get("startDate"), end, dimensional)
    return found


def _number(xbrl: Element) -> str:
    for element in xbrl.iter():
        if _local(element.tag) == "identifier" and "fgov.be" in element.get("scheme", ""):
            digits = "".join(c for c in element.text or "" if c.isdigit())
            if len(digits) == 9:
                digits = "0" + digits
            if len(digits) == 10:
                return digits
    return ""


def _facts(xbrl: Element) -> list[Element]:
    return [e for e in xbrl.iter() if e.get("contextRef")]


def _current(xbrl: Element) -> tuple[date | None, date | None, set[str]]:
    """Exercice en cours : la période sans dimension qui finit le plus tard, et ses contextes."""
    contexts = _contexts(xbrl)
    plain = {k: v for k, v in contexts.items() if not v[2] and v[1] is not None}
    if not plain:
        return None, None, set()
    end = max(v[1] for v in plain.values() if v[1] is not None)
    starts = [v[0] for v in plain.values() if v[1] == end and v[0] is not None]
    current = {k for k, v in plain.items() if v[1] == end}
    return (min(starts) if starts else None), end, current


def _figures(facts: list[Element], current: set[str],
             wanted: tuple[tuple[str, str], ...]) -> list[tuple[str, Decimal]]:  # fmt: skip
    values: dict[str, Decimal] = {}
    for fact in facts:
        name = _local(fact.tag)
        if fact.get("contextRef") in current and name not in values:
            amount = _amount(fact.text)
            if amount is not None:
                values[name] = amount
    return [(label, values[name]) for name, label in wanted if name in values]


def _text(facts: list[Element], name: str) -> str:
    return next(((f.text or "").strip() for f in facts if _local(f.tag) == name), "")


def read(content: bytes) -> Filing | None:
    """Comptes annuels BNB ou déclaration Biztax ; None si ce n'est ni l'un ni l'autre."""
    try:
        root = SafeET.fromstring(content)
    except (SafeET.ParseError, DefusedXmlException, ValueError):
        return None
    if _local(root.tag) == "biztax":
        xbrl = next((c for c in root if _local(c.tag) == "xbrl"), None)
        kind = BIZTAX
    elif _local(root.tag) == "xbrl":
        xbrl = root
        names = " ".join(_namespace(e.tag) for e in root.iter() if e.get("contextRef"))
        if "minfin.fgov.be" in names:
            kind = BIZTAX
        elif "nbb.be" in names:
            kind = ACCOUNTS
        else:
            return None
    else:
        return None
    if xbrl is None:
        return None
    number = _number(xbrl)
    if not number:
        return None
    start, end, current = _current(xbrl)
    facts = _facts(xbrl)
    if kind == ACCOUNTS:
        href = next((e.get("{http://www.w3.org/1999/xlink}href", "") for e in xbrl
                     if _local(e.tag) == "schemaRef"), "")  # fmt: skip
        model = next((label for key, label in MODELS.items() if f"-{key}" in href), "")
        approved = _date(_text(facts, "AccountsApprovalDateGeneralAssembly"))
        return Filing(ACCOUNTS, number, start, end, model=model, approved_on=approved,
                      figures=_figures(facts, current, ACCOUNTS_FIGURES))  # fmt: skip
    year_text = _text(facts, "AssessmentYear")
    tax = RETURN_TYPES.get(_text(facts, "TaxReturnType").lower(), "")
    annexes = [label for name, label in BIZTAX_ANNEXES.items()
               if any(_local(f.tag) == name and (f.text or "").strip() for f in facts)]  # fmt: skip
    return Filing(
        BIZTAX, number, start, end,
        assessment_year=int(year_text) if year_text.isdigit() else None, tax=tax,
        figures=_figures(facts, current, BIZTAX_FIGURES), annexes=annexes,
    )  # fmt: skip
