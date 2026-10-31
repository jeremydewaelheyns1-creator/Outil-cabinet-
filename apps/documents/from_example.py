"""Un modèle à partir d'un document déjà rempli pour un client (D-124).

L'utilisateur dépose une lettre de mission ou un PV d'AG réel, fait pour un client qu'il
désigne. L'outil remplace par des trous tout ce qui est propre à ce client — ce qu'il connaît
de sa fiche (nom, numéro, adresse, gérants, associés, date de clôture) et ce qui se reconnaît
à sa forme (dates, heures, montants, e-mails, IBAN) — puis, si l'assistant IA peut lire les
documents des clients, lui demande ce qui reste (un nom, un lieu…). Le texte du cabinet ne
change pas ; la mise en forme est gardée.

Sécurité : le document d'origine n'est jamais enregistré (lu en mémoire, puis oublié). Le
modèle garde seulement les trous ; le rapport dit combien de choses ont été remplacées, par
sorte, jamais leur valeur. L'administrateur relit le modèle avant de l'activer.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

from apps.clients.models import Client, Relation
from apps.core.cabinet import cabinet_name

from . import letter

MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre")  # fmt: skip

# Repère mis dans le texte → ce que l'outil y remet (sorte de modèle : lettre / pv_ag).
MARKERS: dict[str, dict[str, str]] = {
    "[SOCIÉTÉ]": {"lettre": "client.denomination", "pv_ag": "client.denomination"},
    "[ADRESSE]": {"lettre": "client.adresse", "pv_ag": "client.adresse"},
    "[LOCALITÉ]": {"lettre": "client.localite", "pv_ag": "client.localite"},
    "[VILLE]": {"lettre": "client.ville", "pv_ag": "client.ville"},
    "[NUMÉRO D'ENTREPRISE]": {"lettre": "client.numero", "pv_ag": "client.numero"},
    "[GÉRANT]": {"lettre": "client.representant", "pv_ag": "client.representant"},
    "[ASSOCIÉ]": {"lettre": letter.ASK, "pv_ag": letter.ASK},
    "[DATE DE CLÔTURE]": {"lettre": letter.ASK, "pv_ag": "exercice.cloture"},
    "[DATE]": {"lettre": "date.jour", "pv_ag": "ag.date"},
    "[ANNÉE]": {"lettre": letter.ASK, "pv_ag": "ag.annee"},
    "[NOMBRE]": {"lettre": letter.ASK, "pv_ag": letter.ASK},
    "[HEURE]": {"lettre": letter.ASK, "pv_ag": "ag.debut"},
    "[MONTANT]": {"lettre": letter.ASK, "pv_ag": letter.ASK},
    "[CABINET]": {"lettre": "cabinet.nom", "pv_ag": "cabinet.nom"},
    "[À COMPLÉTER]": {"lettre": letter.ASK, "pv_ag": letter.ASK},
}
# Sorte de chose remplacée (pour le rapport : jamais la valeur).
KINDS = {
    "[SOCIÉTÉ]": "nom du client", "[ADRESSE]": "adresse", "[LOCALITÉ]": "localité",
    "[VILLE]": "ville",
    "[NUMÉRO D'ENTREPRISE]": "numéro d'entreprise", "[GÉRANT]": "gérant ou administrateur",
    "[ASSOCIÉ]": "associé", "[DATE DE CLÔTURE]": "date de clôture", "[DATE]": "date",
    "[HEURE]": "heure", "[MONTANT]": "montant", "[CABINET]": "nom du cabinet",
    "[ANNÉE]": "année", "[NOMBRE]": "nombre de parts",
    "[À COMPLÉTER]": "e-mail, IBAN ou autre",
}  # fmt: skip

DATE = re.compile(
    r"\b\d{1,2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*(?:19|20)\d{2}\b"
    r"|\b(?:1er|\d{1,2})\s+(?:" + "|".join(MONTHS) + r")\s+(?:19|20)\d{2}\b",
    re.I,
)
# « le 23 septembre » (année ailleurs, souvent en lettres) et « deux mille vingt-six ».
DAY_MONTH = re.compile(r"\b(?:1er|\d{1,2})\s+(?:" + "|".join(MONTHS) + r")\b(?!\s+\d)", re.I)
YEAR_WORDS = re.compile(
    r"\bdeux\s+mille(?:[\s-]+(?:et[\s-]+)?(?:un|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|quinze|seize|vingt|trente))*\b",
    re.I,
)
TIME = re.compile(r"\b(?:[01]?\d|2[0-3])\s?(?:h|H|:)\s?[0-5]\d\b|\b(?:[01]?\d|2[0-3])\s?heures?\b")
AMOUNT = re.compile(
    r"(?<![\d.,])\d{1,3}(?:[ .  ]\d{3})*(?:,\d{2})(?![\d])(?:\s?(?:€|EUR|euros?))?"
    r"|(?<![\d.,])\d{1,3}(?:[ .  ]\d{3})+(?![\d,])\s?(?:€|EUR|euros?)"
    r"|(?<![\d.,])\d+\s?(?:€|EUR|euros?)\b",
    re.I,
)
GENERIC = {"cabinet", "fiduciaire", "bureau", "cabinet comptable"}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[0-9A-Z]{4}){2,7}(?:\s?[0-9A-Z]{1,4})?\b")


@dataclass
class Conversion:
    content: bytes
    counts: dict[str, int] = field(default_factory=dict)  # sorte → nombre (jamais la valeur)

    def report(self) -> list[tuple[str, int]]:
        return sorted(self.counts.items(), key=lambda kv: -kv[1])


def _number_pattern(digits: str) -> re.Pattern[str] | None:
    if len(digits) != 10:
        return None
    sep = r"[.\s]?"
    body = sep.join(digits[1:])
    lead = "0?" if digits[0] == "0" else digits[0]
    return re.compile(rf"(?:BE\s?)?{lead}{sep}{body}(?!\d)", re.I)


def _names(person: Client) -> list[str]:
    if not person.is_person:
        return [person.display_name, person.name]
    first, last = person.first_name.strip(), person.name.strip()
    variants = [f"{first} {last}", f"{last} {first}"] if first else []
    return [v for v in variants if v.strip()] + ([last] if len(last) > 3 else [])


def _literal(values: list[str]) -> re.Pattern[str] | None:
    values = sorted({v.strip() for v in values if v and len(v.strip()) > 2}, key=len, reverse=True)
    if not values:
        return None
    # Mots entiers seulement (« Essai » ne prend pas « Essais »).
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(v) for v in values) + r")(?!\w)", re.I)


# Sans fiche : ce qui se reconnaît à sa forme dans un document belge.
ANY_NUMBER = re.compile(r"(?:BE\s?)?[01]\d{3}[.\s]\d{3}[.\s]\d{3}(?!\d)|BE\s?[01]\d{9}(?!\d)")
FORMS = (
    r"(?:S\.?R\.?L\.?|S\.?P\.?R\.?L\.?|S\.?C\.?R\.?L\.?|S\.?A\.?|S\.?C\.?|S\.?N\.?C\.?"
    r"|SComm|A\.?S\.?B\.?L\.?|BV|NV|VZW|Srl|Sa)"
)
FORM_ONLY = re.compile(r"^\s*" + FORMS + r"\s*$")
NAME = r"[A-ZÀ-Ý0-9][\w&'’.-]*"
COMPANY = re.compile(r"(?<![\w&])(?:" + NAME + r"\s+){0,5}" + NAME + r"\s+" + FORMS + r"(?![\w])")
STREET = re.compile(
    r"\b(?:Rue|Avenue|Av\.|Chaussée|Place|Boulevard|Bd|Chemin|Route|Square|Allée|Quai|Drève"
    r"|Clos|Impasse|Sentier|Galerie|Rempart|Parvis|Ruelle|Venelle|Straat|Laan)\b[^,\n]{1,60}?"
    r"\d+[A-Za-z]?(?:\s*(?:,\s*)?(?:bo[iî]te|bte|bus)\s*\w+)?",
    re.I,
)
PLACE = re.compile(r"(?<![\d\w])[1-9]\d{3}\s*[–—-]?\s*[A-ZÀ-Ý][\w'’]+(?:[- ][A-ZÀ-Ý]?[\w'’]+){0,3}")
TOWN = re.compile(r"(?<=[Ff]ait à )(?!X{2,}\b)[A-ZÀ-Ý][\w'’]+(?:-[A-ZÀ-Ý]?[\w'’]+){0,3}")
# « Monsieur Untel », « Mr Prénom Nom », « Mme … » : seul le nom devient un trou ; un nombre
# juste après (« Mr Untel 100 ») = ses parts.
PERSON = re.compile(
    r"\b(?:Monsieur|Madame|Mademoiselle|Mr\.?|Mme\.?|Mlle\.?|M\.)\s+"
    r"(?P<v>(?:[A-ZÀ-Ý][\w'’-]+)(?:\s+[A-ZÀ-Ý][\w'’-]+){0,2})"
)
PARTS = re.compile(
    r"\b(?:Monsieur|Madame|Mr\.?|Mme\.?|M\.)\s+(?:[A-ZÀ-Ý][\w'’-]+\s+){1,3}[–—:-]?\s*"
    r"(?P<v>\d{1,7})(?=\s*(?:parts?|actions?)?\s*$)"
)


def _rules(client: Client | None, closing: list[str]) -> list[tuple[re.Pattern[str], str]]:
    """Ce qui se remplace, dans l'ordre : le plus précis d'abord. Avec la fiche du client
    (retrouvé par son numéro dans le document), on remplace aussi son adresse, ses gérants et
    associés ; sans elle, ce qui se reconnaît à sa forme — l'assistant IA fait le reste."""
    rules: list[tuple[re.Pattern[str] | None, str]] = []
    rules.append((IBAN, "[À COMPLÉTER]"))
    rules.append((EMAIL, "[À COMPLÉTER]"))
    own = cabinet_name().strip()
    if len(own) > 5 and own.lower() not in GENERIC:  # « le cabinet » reste du texte
        rules.append((re.compile(re.escape(own)), "[CABINET]"))
    if client is not None:
        current = Relation.objects.current().select_related("person")
        mine = current.filter(entity=client)
        leaders = [r.person for r in mine.filter(role__in=Relation.MANAGEMENT_ROLES)]
        partners = [r.person for r in mine.filter(role=Relation.Role.SHAREHOLDER)]
        rules.append((_number_pattern(client.enterprise_number or ""), "[NUMÉRO D'ENTREPRISE]"))
        rules.append((_literal([client.display_name, client.name]), "[SOCIÉTÉ]"))
        rules.append((_literal([client.street]), "[ADRESSE]"))
        place = " ".join(v for v in (client.postal_code, client.city) if v)
        rules.append((_literal([place]), "[LOCALITÉ]"))
        rules.append((_literal([client.city]), "[VILLE]"))
        rules.append((_literal([n for p in leaders for n in _names(p)]), "[GÉRANT]"))
        others = [p for p in partners if p not in leaders]
        rules.append((_literal([n for p in others for n in _names(p)]), "[ASSOCIÉ]"))
        rules.append((_literal(closing), "[DATE DE CLÔTURE]"))
    rules.append((ANY_NUMBER, "[NUMÉRO D'ENTREPRISE]"))
    rules.append((COMPANY, "[SOCIÉTÉ]"))
    rules.append((STREET, "[ADRESSE]"))
    rules.append((PLACE, "[LOCALITÉ]"))
    rules.append((TOWN, "[VILLE]"))
    rules.append((PARTS, "[NOMBRE]"))
    rules.append((PERSON, "[GÉRANT]"))
    rules.append((DATE, "[DATE]"))
    rules.append((DAY_MONTH, "[DATE]"))
    rules.append((YEAR_WORDS, "[ANNÉE]"))
    rules.append((TIME, "[HEURE]"))
    rules.append((AMOUNT, "[MONTANT]"))
    return [(p, m) for p, m in rules if p is not None]


def client_in(content: bytes, clients: Any) -> Client | None:
    """Le client du document, retrouvé par le numéro d'entreprise imprimé (parmi les dossiers
    visibles de la personne) ; aucun ou plusieurs : aucun."""
    from apps.vat import intervat

    text = text_of(content)
    numbers = {intervat.normalize_number(m) for m in ANY_NUMBER.findall(text)} - {""}
    found = list(clients.filter(enterprise_number__in=numbers)[:2]) if numbers else []
    return found[0] if len(found) == 1 else None


def _closing_dates(client: Client) -> list[str]:
    from apps.closing.models import ClosingYear

    found = []
    for year in ClosingYear.objects.filter(client=client):
        end = year.end
        found += [f"{end:%d/%m/%Y}", f"{end:%d.%m.%Y}", f"{end:%d-%m-%Y}",
                  f"{end.day} {MONTHS[end.month - 1]} {end.year}"]  # fmt: skip
    return found


def _spans(text: str, rules: list[tuple[re.Pattern[str], str]],
           extra: list[tuple[str, str]]) -> list[tuple[int, int, str]]:  # fmt: skip
    """Endroits à remplacer, sans chevauchement (le premier qui couvre gagne)."""
    taken: list[tuple[int, int, str]] = []

    def free(start: int, end: int) -> bool:
        return all(end <= s or start >= e for s, e, _ in taken)

    for value, marker in extra:  # ce que l'assistant a trouvé : valeurs exactes
        for match in re.finditer(re.escape(value), text):
            if free(match.start(), match.end()):
                taken.append((match.start(), match.end(), marker))
    for pattern, marker in rules:
        for match in pattern.finditer(text):
            group = "v" if "v" in pattern.groupindex else 0  # seulement la partie utile
            start, end = match.start(group), match.end(group)
            if match.group(group).strip() and free(start, end):
                taken.append((start, end, marker))
    return sorted(taken)


def convert(
    content: bytes, client: Client | None = None, extra: list[tuple[str, str]] | None = None
) -> Conversion:
    """Le document rempli devient un modèle (fichier Word) : les valeurs du client deviennent
    des repères entre crochets, que l'outil sait remplir."""
    document = letter._open(content)
    rules = _rules(client, _closing_dates(client) if client is not None else [])
    counts: dict[str, int] = {}
    paragraphs = letter._paragraphs(document)
    names = _name_lines(paragraphs)
    for index, paragraph in enumerate(paragraphs):
        text = paragraph.text
        if not text.strip():
            continue
        if index in names and "[" not in text:
            whole = [(len(text) - len(text.lstrip()), len(text.rstrip()), "[SOCIÉTÉ]")]
            letter._fill(paragraph, whole)
            counts["nom du client"] = counts.get("nom du client", 0) + 1
            continue
        spans = _spans(text, rules, extra or [])
        if spans:
            letter._fill(paragraph, spans)
            for _, _, marker in spans:
                kind = KINDS.get(marker, "autre")
                counts[kind] = counts.get(kind, 0) + 1
    out = io.BytesIO()
    document.save(out)
    return Conversion(out.getvalue(), counts)


def _name_lines(paragraphs: list[Any]) -> set[int]:
    """En-tête « NOM » puis « S.R.L. » sur la ligne suivante : la ligne du nom est le nom du
    client."""
    found: set[int] = set()
    previous = None
    for index, paragraph in enumerate(paragraphs):
        text = paragraph.text.strip()
        if not text:
            continue
        if FORM_ONLY.match(text) and previous is not None:
            prev_text = paragraphs[previous].text.strip()
            if 0 < len(prev_text) <= 60 and not FORM_ONLY.match(prev_text):
                found.add(previous)
        previous = index
    return found


def text_of(content: bytes) -> str:
    return "\n".join(p.text for p in letter._paragraphs(letter._open(content)) if p.text.strip())


def holes_for(content: bytes, kind: str) -> dict[str, dict[str, Any]]:
    """Contenu de chaque trou du modèle obtenu : d'après le repère posé ; sinon la proposition
    habituelle (pour les trous qui existaient déjà dans le document)."""
    result: dict[str, dict[str, Any]] = {}
    rows = _row_labels(content)
    for hole in letter.holes(content, kind):
        marker = hole.text.strip().upper()
        field_code = (MARKERS.get(marker) or {}).get(kind, "")
        if marker == "[HEURE]" and kind == "pv_ag":
            low = hole.before.lower()[-40:]
            field_code = (
                "ag.fin"
                if any(w in low for w in ("levée", "levee", "clôtur", "fin"))
                else "ag.debut"
            )
        if marker == "[DATE]" and kind == "pv_ag":
            low = hole.before.lower()[-30:]
            if any(w in low for w in ("arrêté", "arrete", "clôtur", "clotur", "exercice")):
                field_code = "exercice.cloture"
        if not field_code:
            field_code = hole.guess
        if not field_code:
            continue
        label = ""
        if field_code == letter.ASK:
            index = int(hole.key.split(":")[0])
            label = rows.get(index) or _label(hole.before) or KINDS.get(marker, "").capitalize()
            if marker == "[NOMBRE]":
                label = "Nombre de parts"
        result[hole.key] = {"field": field_code, "label": label[:120]}
    return result


def _row_labels(content: bytes) -> dict[int, str]:
    """Trou dans un tableau : la question est le libellé de sa ligne (« ATN Auto »)."""
    from docx.oxml.ns import qn

    labels: dict[int, str] = {}
    for index, paragraph in enumerate(letter._paragraphs(letter._open(content))):
        row = paragraph._p
        while row is not None and row.tag != qn("w:tr"):
            row = row.getparent()
        if row is None:
            continue
        for cell in row.findall(qn("w:tc")):
            text = "".join(t.text or "" for t in cell.iter(qn("w:t")))
            clean = _clean(text)
            if clean and "[" not in text:
                labels[index] = clean
                break
    return labels


def _clean(text: str) -> str:
    text = re.sub(r"\[[^\]]*\]|\([+-]\)|[€•\-–+:]", " ", text)
    words = text.split()
    return " ".join(words)[:1].upper() + " ".join(words)[1:] if words else ""


STOP = {"soit", "de", "du", "des", "à", "a", "au", "aux", "la", "le", "les", "un", "une", "par",
        "est", "sont", "pour", "et", "en", "qui", "que"}  # fmt: skip


def _label(before: str) -> str:
    """Hors tableau : les derniers mots utiles avant le trou (« bénéfice de l'exercice »)."""
    text = re.sub(r"\[[^\]]*\]", " ", before)
    parts = [p for p in re.split(r"[.;:!?\n]", text) if p.strip()]
    text = parts[-1] if parts else ""
    words = [w for w in re.sub(r"[(),€+–-]", " ", text).split()]
    while words and words[-1].lower() in STOP:
        words.pop()
    words = words[-6:]
    while words and words[0].lower() in STOP:
        words.pop(0)
    label = " ".join(words)
    return label[:1].upper() + label[1:]
