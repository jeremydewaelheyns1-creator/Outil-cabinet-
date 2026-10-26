"""Lettre de mission sur le modèle Word du cabinet (D-069).

1. Un administrateur dépose le modèle **tel quel** : l'outil repère les trous (« XXX »,
   « …… », « ____ », « [à compléter] », texte surligné) et propose ce que chacun contient
   d'après les mots qui précèdent (« siège social XXX » → adresse du siège).
2. Il confirme ou corrige chaque trou, choisit les paragraphes à options (gardés seulement si
   le client est assujetti TVA, une société…), et confirme les éléments obligatoires de
   l'ITAA que l'outil a retrouvés dans le texte. Un élément obligatoire absent : le modèle ne
   peut pas être utilisé.
3. Pour chaque client, l'outil remplit les trous (fiche + réponses du comptable), retire les
   paragraphes non retenus et produit le PDF à faire signer en ligne.

Le texte du cabinet n'est jamais réécrit : seuls les trous changent. Aucune IA.
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.html import escape

from apps.clients.models import Client, Relation
from apps.core.text import normalize_text

MAX_SIZE = 5 * 1024 * 1024
HOLE = re.compile(r"X{3,}|x{3,}|\.{4,}|…{2,}|_{4,}|\[[^\]\n]{1,60}\]")
ASK = "demander"  # contenu demandé au comptable à chaque lettre
KEEP = "laisser"  # pas un trou : laissé tel quel


def _representative(client: Client) -> str:
    link = (
        Relation.objects.current()
        .filter(entity=client, role__in=Relation.MANAGEMENT_ROLES)
        .select_related("person")
        .order_by("role", "person__name")
        .first()
    )
    if link is None:
        return ""
    person = link.person
    return f"{person.first_name} {person.name}".strip() if person.is_person else person.display_name


# Ce que l'outil sait remplir tout seul : code → (libellé, valeur pour un client).
FIELDS: dict[str, tuple[str, Callable[[Client], str]]] = {
    "client.denomination": ("Dénomination / nom du client", lambda c: c.display_name),
    "client.forme": ("Forme juridique", lambda c: c.legal_form or ""),
    "client.numero": ("Numéro d'entreprise", lambda c: c.enterprise_number_display or ""),
    "client.siege": ("Adresse (siège social)", lambda c: ", ".join(c.address_lines)),
    "client.representant": ("Représentant du client (gérant, administrateur)", _representative),
    "cabinet.nom": ("Nom du cabinet", lambda c: settings.CABINET_NAME),
    "date.jour": ("Date du jour", lambda c: f"{timezone.localdate():%d/%m/%Y}"),
}
CHOICES: list[tuple[str, str]] = [
    *[(code, label) for code, (label, _) in FIELDS.items()],
    (ASK, "À demander à chaque lettre (honoraires, lieu, date de début…)"),
    (KEEP, "Pas un trou : laisser tel quel"),
]

# Paragraphes à options : gardés seulement si…
CONDITIONS: dict[str, str] = {
    "": "Toujours",
    "tva": "Seulement si le client est assujetti à la TVA",
    "societe": "Seulement pour une société ou une ASBL",
    "personne": "Seulement pour une personne physique",
    "question": "Seulement si le comptable le coche (ex. IPP du dirigeant, nouveau client)",
}

# Éléments obligatoires de la lettre de mission selon l'ITAA, et mots qui les signalent.
REQUIRED: list[tuple[str, str, tuple[str, ...]]] = [
    ("parties", "Identification des deux parties", ("entre", "client")),
    (
        "debut",
        "Date de début de la mission",
        ("prend cours", "debut", "a partir du", "commence", "entre en vigueur", "exercice"),
    ),
    (
        "fin",
        "Façon de mettre fin à la mission",
        ("resili", "fin de la convention", "mettre fin", "preavis", "rupture"),
    ),
    ("honoraires", "Honoraires, paiement et facturation", ("honoraire",)),
    ("documents", "Remise et conservation des documents", ("conserv", "documents")),
    ("litiges", "Règlement des litiges", ("litige", "tribuna", "mediation", "arbitr")),
    ("representant", "Représentant du cabinet", ("represente",)),
    (
        "signature",
        "Signature des deux parties",
        ("signature", "signe", "lu et approuve", "exemplaire"),
    ),
]
RECOMMENDED: list[tuple[str, str, tuple[str, ...]]] = [
    (
        "blanchiment",
        "Clause anti-blanchiment (pièces d'identité avant de commencer)",
        ("blanchiment",),
    ),
    (
        "rgpd",
        "Protection des données personnelles (RGPD)",
        ("donnees personnelles", "rgpd", "vie privee"),
    ),
    ("secret", "Secret professionnel", ("secret professionnel",)),
]


def _paragraphs(document: Any) -> list[Any]:
    """Tous les paragraphes du corps, tableaux compris, dans l'ordre du document."""
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph

    body = document.element.body
    return [Paragraph(p, document) for p in body.iter(qn("w:p"))]


def _open(content: bytes) -> Any:
    from docx import Document as Word

    try:
        return Word(io.BytesIO(content))
    except Exception as exc:  # fichier abîmé ou pas un Word
        raise ValidationError("Ce fichier n'est pas un document Word (.docx) lisible.") from exc


@dataclass
class Hole:
    key: str  # « paragraphe:position »
    before: str
    text: str
    after: str
    guess: str


def _highlighted(paragraph: Any) -> list[str]:
    from docx.oxml.ns import qn

    found: list[str] = []
    for run in paragraph.runs:
        if run._element.find(".//" + str(qn("w:highlight"))) is not None and run.text.strip():
            found.append(run.text)
    return found


def _guess(before: str, after: str) -> str:
    b, a = normalize_text(before)[-60:], normalize_text(after)[:25]
    rules: list[tuple[Callable[[], bool], str]] = [
        (
            lambda: "siege" in b[-30:] or "domicil" in b[-30:] or "adresse" in b[-25:],
            "client.siege",
        ),
        (
            lambda: "numero" in b[-25:] or "bce" in b[-25:] or "entreprises" in b[-30:],
            "client.numero",
        ),
        (
            lambda: "represent" in b[-35:] or "gerant" in b[-20:] or "administrat" in b[-20:],
            "client.representant",
        ),
        (
            lambda: (
                "eur" in a or "€" in after[:10] or "montant" in b[-20:] or "honoraire" in b[-30:]
            ),
            ASK,
        ),
        (lambda: b.rstrip().endswith("fait a") or "exercice" in b[-20:], ASK),
        (lambda: b.rstrip().endswith(" le") and "fait a" in b, "date.jour"),
        (lambda: "forme" in b[-20:], "client.forme"),
        (
            lambda: b.rstrip().endswith((" la", " le", "et d autre part", "societe")),
            "client.denomination",
        ),
    ]
    for test, code in rules:
        if test():
            return code
    return ""


def _spans(paragraph: Any) -> list[tuple[int, int]]:
    """Positions des trous dans le texte du paragraphe, dans l'ordre."""
    text = paragraph.text
    spans = [(m.start(), m.end()) for m in HOLE.finditer(text)]
    for marked in _highlighted(paragraph):
        position = text.find(marked)
        if position >= 0 and not any(s <= position < e for s, e in spans):
            spans.append((position, position + len(marked)))
    return sorted(spans)


def holes(content: bytes) -> list[Hole]:
    """Trous repérés dans le modèle, avec le texte autour et une proposition."""
    result: list[Hole] = []
    running = ""
    for index, paragraph in enumerate(_paragraphs(_open(content))):
        text = paragraph.text
        for number, (start, end) in enumerate(_spans(paragraph)):
            before = (running + " " + text[:start]).strip()[-80:]
            after = text[end:][:60]
            guess = _guess(before, after)
            result.append(Hole(f"{index}:{number}", before, text[start:end], after, guess))
        running = (running + " " + text)[-200:]
    return result


def paragraphs(content: bytes) -> list[tuple[int, str]]:
    """Les paragraphes non vides (pour choisir ceux qui sont à options)."""
    return [(i, p.text) for i, p in enumerate(_paragraphs(_open(content))) if p.text.strip()]


@dataclass
class Check:
    code: str
    label: str
    excerpt: str
    required: bool


def checks(content: bytes, hole_map: dict[str, Any]) -> list[Check]:
    """Éléments de l'ITAA retrouvés (avec l'extrait) ou absents (extrait vide)."""
    texts = [t for _, t in paragraphs(content)]
    plain = [normalize_text(t) for t in texts]
    mapped = {v.get("field") for v in hole_map.values() if isinstance(v, dict)}
    result = []
    for required, items in ((True, REQUIRED), (False, RECOMMENDED)):
        for code, label, words in items:
            excerpt = ""
            for original, low in zip(texts, plain, strict=True):
                if any(w in low for w in words):
                    excerpt = original.strip()[:180]
                    break
            if code == "parties" and "client.denomination" not in mapped:
                excerpt = ""
            result.append(Check(code, label, excerpt, required))
    return result


def problems(template: Any) -> list[str]:
    """Ce qui empêche encore d'utiliser le modèle (vide : prêt)."""
    content = bytes(template.content)
    found = []
    unknown = [h for h in holes(content) if not (template.holes.get(h.key) or {}).get("field")]
    if unknown:
        found.append(f"{len(unknown)} trou(s) sans contenu choisi")
    for check in checks(content, template.holes):
        if check.required and not check.excerpt:
            found.append(f"Élément obligatoire absent du modèle : {check.label}")
        elif check.required and check.code not in template.checks:
            found.append(f"À confirmer : {check.label}")
    return found


def questions(template: Any) -> list[tuple[str, str]]:
    """Ce que le comptable doit donner à chaque lettre : (clé, libellé)."""
    asked = []
    for key, value in template.holes.items():
        if isinstance(value, dict) and value.get("field") == ASK:
            asked.append((f"trou:{key}", value.get("label") or "Information à compléter"))
    for start, value in sorted(template.options.items(), key=lambda kv: int(kv[0])):
        if value.get("condition") == "question":
            asked.append((f"option:{start}", value.get("label") or "Inclure ce passage ?"))
    return sorted(asked, key=lambda q: _order(q[0]))


def _order(key: str) -> tuple[int, int]:
    kind, _, rest = key.partition(":")
    head = rest.split(":")[0]
    return (int(head) if head.isdigit() else 0, 0 if kind == "trou" else 1)


def _keep(condition: str, client: Client, answer: bool) -> bool:
    if condition == "tva":
        return client.vat_status in ("subject", "mixed")
    if condition == "societe":
        return not client.is_person
    if condition == "personne":
        return client.is_person
    if condition == "question":
        return answer
    return True


def _fill(paragraph: Any, replacements: list[tuple[int, int, str]]) -> None:
    """Remplace les trous en ne touchant qu'aux passages qu'ils couvrent : le reste du paragraphe
    (gras, italique…) garde la mise en forme du cabinet."""
    runs = paragraph.runs
    for start, end, value in sorted(replacements, reverse=True):
        position, covered = 0, []
        for run in runs:
            length = len(run.text)
            if position < end and position + length > start:
                covered.append((run, position))
            position += length
        if not covered:
            continue
        first, offset = covered[0]
        last, last_offset = covered[-1]
        head = first.text[: start - offset]
        tail = last.text[end - last_offset :]
        if first is last:
            first.text = head + value + tail
        else:
            first.text = head + value
            for run, _ in covered[1:-1]:
                run.text = ""
            last.text = tail
        rpr = first._element.rPr
        if rpr is not None and rpr.highlight is not None:  # le surlignage du trou disparaît
            rpr.remove(rpr.highlight)


def fill(template: Any, client: Client, answers: dict[str, str]) -> bytes:
    """Le modèle rempli pour ce client (fichier Word)."""
    document = _open(bytes(template.content))
    items = _paragraphs(document)
    for index, paragraph in enumerate(items):
        replacements = []
        for number, (start, end) in enumerate(_spans(paragraph)):
            key = f"{index}:{number}"
            code = (template.holes.get(key) or {}).get("field", "")
            if not code or code == KEEP or (code != ASK and code not in FIELDS):
                continue
            value = answers.get(f"trou:{key}", "") if code == ASK else FIELDS[code][1](client)
            replacements.append((start, end, value))
        if replacements:
            _fill(paragraph, replacements)
    removed: set[int] = set()
    for start, end, condition in blocks(template.options):
        if not _keep(condition, client, answers.get(f"option:{start}") == "1"):
            removed.update(range(start, end + 1))
    for index in sorted(removed, reverse=True):
        if index < len(items):
            element = items[index]._element
            element.getparent().remove(element)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


PDF_STYLE = (
    "@page{size:A4;margin:22mm 20mm}"
    "body{font-family:'DejaVu Serif',serif;font-size:10.5pt;line-height:1.45;color:#1b2430}"
    "table{border-collapse:collapse;width:100%}"
    "td,th{border:1px solid #c9d1dc;padding:5px 7px;vertical-align:top}"
    "h1,h2,h3{color:#14243b} p{margin:0 0 7px}"
)


def to_pdf(word: bytes, title: str) -> bytes:
    """PDF de la lettre remplie (mise en page simple, fidèle au texte du cabinet)."""
    import mammoth
    from weasyprint import HTML

    html = mammoth.convert_to_html(io.BytesIO(word)).value
    page = (
        f"<!DOCTYPE html><html lang='fr'><head><meta charset='utf-8'><title>{escape(title)}"
        f"</title><style>{PDF_STYLE}</style></head><body>{html}</body></html>"
    )
    return bytes(HTML(string=page, url_fetcher=_local_only).write_pdf())


def _local_only(url: str, *args: Any, **kwargs: Any) -> Any:
    """Le PDF n'accède à rien d'extérieur : seules les images intégrées au Word passent."""
    from weasyprint import default_url_fetcher

    if not url.startswith("data:"):
        raise ValueError("Ressource externe refusée")
    return default_url_fetcher(url, *args, **kwargs)


def active() -> Any:
    from .models import LetterTemplate

    return LetterTemplate.objects.filter(active=True).first()


def check_upload(name: str, content: bytes) -> None:
    if not name.lower().endswith(".docx"):
        raise ValidationError("Déposez le modèle au format Word (.docx).")
    if len(content) > MAX_SIZE:
        raise ValidationError("Fichier trop lourd (5 Mo au maximum).")
    _open(content)


def blocks(options: dict[str, Any]) -> Iterator[tuple[int, int, str]]:
    for start, value in options.items():
        yield int(start), int(value.get("end", start)), value.get("condition", "")
