"""Lecture d'un modèle Word par l'assistant IA (D-132) : il reçoit le document ENTIER, avec sa
structure (paragraphes, tableaux et leurs lignes), et rend la carte de ce qui change d'un client
à l'autre — ce que l'outil remplit depuis la fiche, ce qu'il demande à chaque document — comme
le ferait un collaborateur du cabinet. Les règles de l'outil passent derrière, en garde-fous.

Le comptable n'a rien à faire : l'assistant travaille au dépôt du modèle, en coulisse (D-127).
Il voit l'aperçu coloré du résultat et corrige d'un clic ; ses corrections deviennent des
exemples pour les prochains modèles (`CabinetSettings.ai_examples`).

Sécurité : un document déposé peut être rempli pour un vrai client ; il n'est envoyé que si le
cabinet l'autorise (zéro conservation confirmé, `personal=True`), numéros et e-mails masqués
(`privacy.mask`). Rien n'est gardé du document d'origine : seul le modèle obtenu l'est."""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from typing import Any

from apps.core.models import User
from apps.core.text import normalize_text
from apps.documents import letter

from . import client as ai
from . import privacy

MODEL = "mistral-large-latest"  # lecture fine d'un document : le modèle le plus soigné

# Nom court du repère posé dans le modèle, selon ce que l'outil y remet.
MARKER_NAMES = {
    "client.denomination": "Société", "client.forme": "Forme juridique",
    "client.numero": "Numéro d'entreprise", "client.siege": "Siège",
    "client.adresse": "Adresse", "client.localite": "Code postal et localité",
    "client.ville": "Ville", "client.representant": "Gérant",
    "client.dirigeants": "Dirigeants", "client.associes": "Associés",
    "cabinet.nom": "Cabinet", "date.jour": "Date", "ag.date": "Date de l'AG",
    "ag.date_longue": "Date de l'AG", "ag.annee": "Année", "ag.debut": "Heure d'ouverture",
    "ag.fin": "Heure de clôture", "exercice.debut": "Début de l'exercice",
    "exercice.cloture": "Clôture de l'exercice", "ag.autres": "Résolutions supplémentaires",
}  # fmt: skip
# Ce que l'outil met lui-même, avec un chiffre dedans dans un document rempli.
FIGURES = {"ag.date", "ag.annee", "ag.debut", "ag.fin", "exercice.debut", "exercice.cloture",
           "date.jour", "client.numero"}  # fmt: skip
# Fiche du client : le même texte ailleurs dans le document est la même donnée.
SPREAD = {"client.denomination", "client.representant", "client.dirigeants", "client.adresse",
          "client.siege", "client.localite", "client.numero"}  # fmt: skip
CONDITIONS = {"dividende", "sans_dividende", "tva", "societe", "personne"}

SYSTEM = """Tu es un collaborateur expérimenté d'un cabinet comptable belge. On te donne un
modèle Word du cabinet ({sorte}), découpé en blocs numérotés (P0, P1…). Un bloc qui est une case
de tableau est présenté avec sa ligne entière, pour que tu voies le libellé et le montant.

Le cabinet va réutiliser ce document pour TOUS ses clients. Ta mission : repérer chaque élément
qui CHANGE d'un client à l'autre ou d'une année à l'autre, et dire ce que l'outil doit y mettre.

Le document peut être :
- déjà rempli pour un client (de vrais noms, adresses, dates, montants) : repère ces valeurs ;
- un modèle vide avec des repères ([LIEU DE REUNION], XXX, ……) : repère chaque repère.

Pour chaque élément, donne :
- "bloc" : le numéro du bloc (ex. "P12") ;
- "texte" : la partie qui change, recopiée EXACTEMENT, la plus courte possible
  (« Agence Test Immo SRL », « 100.000,00 », « 18h00 », « [LIEU DE REUNION] ») — jamais la
  phrase entière, jamais le symbole € ni le mot qui précède ;
- "code" : ce que l'outil y met, choisi dans la liste des codes ;
- "intitule" : seulement pour le code "demander" — la question posée au comptable, courte, avec
  les mots du document (pour une ligne de tableau : son libellé exact, ex. « ATN Auto »), sans
  point d'interrogation, différente pour chaque élément.

Règles :
- Ce qui est dans la fiche du client (nom, forme, numéro, adresse, gérant, associés) : le code
  de la fiche, pas "demander".
- Montants, nombres de parts, lieu de réunion, objet d'une modification : "demander".
- Date et heures de l'assemblée, année de l'assemblée, date de clôture de l'exercice : les codes
  ag.* / exercice.* (même écrites en lettres : « deux mille vingt-six »).
- Le texte du cabinet ne change pas : titres, formules juridiques, libellés des lignes d'un
  tableau (« Bénéfice d'exploitation », « ATN Auto »), numéros de résolution, mots comme
  « Administrateur » ou « Monsieur le Président », le nom du cabinet lui-même. Ne les propose
  jamais.
- Une même valeur répétée dans plusieurs blocs : un élément par bloc.
- Dans le doute, ne propose rien.

Indique aussi les blocs qui ne valent que dans certains cas, avec une condition parmi : {conditions}
(ex. « reporter l'intégralité du bénéfice » → "sans_dividende" ; « distribuer un dividende » →
"dividende"). Dans le doute, rien.

Codes possibles :
{codes}

Réponds uniquement en JSON :
{{"elements": [{{"bloc": "P0", "texte": "...", "code": "...", "intitule": "..."}}],
 "passages": [{{"bloc": "P0", "condition": "..."}}]}}
"""

EXAMPLE_IN = """P0: Boulangerie Fictive SRL
P1: Rue du Four 12
P2: 5000 Namur
P3: L'an deux mille vingt-cinq, le 20 juin, l'assemblée s'est tenue au siège social \
à 18h00 sous la présidence de Monsieur Paul Essai.
P4 [tableau 1, ligne 1] : - Bénéfice d'exploitation | (+) | € | 52.300,00
P5 [tableau 1, ligne 2] : - Bénéfice net à affecter | | € | 40.000,00
P6: L'assemblée décide de reporter l'intégralité du bénéfice, soit 40.000,00 €.
P7: Décharge est donnée à Monsieur Paul Essai, gérant.
P8: La séance est levée à 18h45."""
EXAMPLE_OUT = {
    "elements": [
        {"bloc": "P0", "texte": "Boulangerie Fictive SRL", "code": "client.denomination"},
        {"bloc": "P1", "texte": "Rue du Four 12", "code": "client.adresse"},
        {"bloc": "P2", "texte": "5000 Namur", "code": "client.localite"},
        {"bloc": "P3", "texte": "deux mille vingt-cinq", "code": "ag.annee"},
        {"bloc": "P3", "texte": "20 juin", "code": "ag.date"},
        {"bloc": "P3", "texte": "18h00", "code": "ag.debut"},
        {"bloc": "P3", "texte": "Paul Essai", "code": "client.representant"},
        {"bloc": "P4", "texte": "52.300,00", "code": "demander",
         "intitule": "Bénéfice d'exploitation"},
        {"bloc": "P5", "texte": "40.000,00", "code": "demander",
         "intitule": "Bénéfice net à affecter"},
        {"bloc": "P6", "texte": "40.000,00", "code": "demander",
         "intitule": "Bénéfice reporté"},
        {"bloc": "P7", "texte": "Paul Essai", "code": "client.representant"},
        {"bloc": "P8", "texte": "18h45", "code": "ag.fin"},
    ],
    "passages": [{"bloc": "P6", "condition": "sans_dividende"}],
}  # fmt: skip


@dataclass
class Reading:
    """Le modèle obtenu et ce que l'assistant a compris de chaque repère qu'il a posé."""

    content: bytes
    # paragraphe → repères posés, dans l'ordre : (texte du repère, code, intitulé)
    marks: dict[int, list[tuple[str, str, str]]] = field(default_factory=dict)
    options: dict[str, dict[str, Any]] = field(default_factory=dict)
    replaced: int = 0  # valeurs d'un client remplacées (document rempli)
    refused: int = 0  # propositions écartées par les garde-fous


def blocks(content: bytes) -> list[tuple[int, str]]:
    """Le document en blocs « P12: texte » ; une ligne de tableau est un seul bloc, ses cases
    séparées par « | » (le numéro est celui de sa première case remplie)."""
    from docx.oxml.ns import qn

    document = letter._open(content)
    tree = document.element.getroottree()
    tables = {tree.getpath(t): n for n, t in enumerate(document.element.body.iter(qn("w:tbl")), 1)}
    lines: list[tuple[int, str]] = []
    seen_rows: set[str] = set()
    for index, paragraph in enumerate(letter._paragraphs(document)):
        text = paragraph.text
        if not text.strip():
            continue
        row = paragraph._p
        while row is not None and row.tag != qn("w:tr"):
            row = row.getparent()
        if row is None:
            lines.append((index, f"P{index}: {text}"))
            continue
        table = row.getparent()
        number = list(table.findall(qn("w:tr"))).index(row) + 1
        cells = [
            "".join(t.text or "" for t in cell.iter(qn("w:t"))).strip()
            for cell in row.findall(qn("w:tc"))
        ]
        where = f"tableau {tables.get(tree.getpath(table), '?')}, ligne {number}"
        path = tree.getpath(row)
        if path not in seen_rows:  # une ligne de tableau = un bloc, toutes ses cases
            seen_rows.add(path)
            lines.append((index, f"P{index} [{where}] : {' | '.join(cells)}"))
    return lines


def _codes(kind: str) -> str:
    return "\n".join(
        f"- {code} : {label}" for code, label in letter.choices(kind) if code != letter.KEEP
    )


def _examples() -> str:
    """Les corrections faites par le cabinet sur des modèles précédents (ses habitudes)."""
    from apps.core.models import CabinetSettings

    found = CabinetSettings.current().ai_examples or []
    if not found:
        return ""
    lines = []
    for example in found[-20:]:
        line = f"- « {example.get('contexte', '')} » → {example.get('code', '')}"
        if example.get("intitule"):
            line += f" (« {example['intitule']} »)"
        lines.append(line)
    return "\n\nCorrections déjà faites par ce cabinet (fais pareil) :\n" + "\n".join(lines)


def ask(content: bytes, kind: str, user: User | None) -> dict[str, Any]:
    """La réponse brute de l'assistant pour ce document (lève `ai.Unavailable`)."""
    sorte = "PV d'assemblée générale" if kind == "pv_ag" else "lettre de mission"
    system = (
        SYSTEM.format(sorte=sorte, codes=_codes(kind), conditions=", ".join(sorted(CONDITIONS)))
        + _examples()
    )
    document = "\n".join(privacy.mask(line[:1500]) for _, line in blocks(content))
    prompt = (
        "Exemple (document fictif) :\n" + EXAMPLE_IN + "\nRéponse attendue :\n"
        + json.dumps(EXAMPLE_OUT, ensure_ascii=False)
        + "\n\nDocument à analyser :\n" + document[:60000]
    )  # fmt: skip
    answer = ai.ask_json("lecture_modele", system, prompt, user=user, personal=True, model=MODEL)
    return answer.data


def read(content: bytes, kind: str, user: User | None) -> Reading:
    """Le modèle obtenu : chaque élément repéré par l'assistant devient un repère « [Société] »,
    « [ATN Auto] »… dans la mise en forme du document. Lève `ai.Unavailable`."""
    return apply(content, kind, ask(content, kind, user))


def _protected(content: bytes) -> list[str]:
    """Ce que l'assistant ne remplace jamais : libellés de lignes de tableau, nom du cabinet."""
    from apps.core.cabinet import cabinet_name
    from apps.documents import from_example

    found = from_example.row_texts(content)
    own = cabinet_name().strip()
    if len(own) > 5:
        found.append(own)
    return found


def _ok(value: str, code: str, protected: list[str], placeholder: bool) -> bool:
    """Garde-fous sur une proposition de l'assistant."""
    if placeholder:
        return True  # un repère du modèle vide : toujours un trou
    if any(value in text and not re.search(r"\d", value) for text in protected):
        return False  # libellé de ligne, nom du cabinet
    if code in FIGURES and code != "ag.annee":
        months = r"janv|févr|fevr|mars|avril|mai|juin|juil|août|aout|sept|oct|nov|déc|dec"
        in_words = code == "ag.date" and bool(re.search(months, value, re.I))
        return bool(re.search(r"\d", value)) or in_words
    if code == "ag.annee":
        return bool(re.search(r"\d|mille", value, re.I))
    if code == letter.ASK:
        return True
    return bool(re.search(r"[A-Za-zÀ-ÿ\d]", value)) and len(value.split()) <= 12


def _marker(code: str, label: str) -> str:
    name = MARKER_NAMES.get(code) or label or "À compléter"
    name = re.sub(r"[\[\]\n]", " ", name).strip()[:55] or "À compléter"
    return f"[{name}]"


def apply(content: bytes, kind: str, data: dict[str, Any]) -> Reading:
    """Applique la carte de l'assistant au document (sans réseau : testable, rejouable)."""
    document = letter._open(content)
    paragraphs = letter._paragraphs(document)
    rows = _rows(document, paragraphs)
    allowed = {code for code, _ in letter.choices(kind)} - {letter.KEEP}
    protected = _protected(content)
    wanted: dict[int, list[tuple[str, str, str]]] = {}
    refused = 0
    for item in (data.get("elements") or [])[:400]:
        if not isinstance(item, dict):
            continue
        match = re.fullmatch(r"P(\d+)", str(item.get("bloc") or "").strip())
        value = str(item.get("texte") or "")
        code = str(item.get("code") or "")
        label = re.sub(r"\s+", " ", str(item.get("intitule") or "")).strip().rstrip("?").strip()
        if not match or not value.strip() or code not in allowed:
            refused += 1
            continue
        index = int(match.group(1))
        # Bloc d'une ligne de tableau : la valeur est dans l'une de ses cases.
        index = next((i for i in rows.get(index, [index])
                      if i < len(paragraphs) and value in paragraphs[i].text), -1)  # fmt: skip
        if index < 0:
            refused += 1
            continue
        placeholder = bool(letter.HOLE.fullmatch(value.strip()))
        if not _ok(value, code, protected, placeholder):
            refused += 1
            continue
        wanted.setdefault(index, []).append((value, code, label[:120]))
    _spread(paragraphs, wanted, protected)
    reading = Reading(b"", refused=refused)
    for index, items in wanted.items():
        paragraph = paragraphs[index]
        text = paragraph.text
        spans: list[tuple[int, int, str, str, str]] = []
        for value, code, label in items:
            start = 0
            while True:
                position = text.find(value, start)
                if position < 0:
                    break
                end = position + len(value)
                if all(end <= s or position >= e for s, e, *_ in spans):
                    spans.append((position, end, value, code, label))
                    break
                start = position + 1
        spans.sort()
        replacements = []
        marks = []
        for start, end, value, code, label in spans:
            placeholder = bool(letter.HOLE.fullmatch(value.strip()))
            marker = value if placeholder else _marker(code, label)
            replacements.append((start, end, marker))
            marks.append((marker, code, label))
            reading.replaced += 0 if placeholder else 1
        letter._fill(paragraph, replacements)
        reading.marks[index] = marks
    for item in data.get("passages") or []:
        if not isinstance(item, dict):
            continue
        match = re.fullmatch(r"P(\d+)", str(item.get("bloc") or "").strip())
        condition = str(item.get("condition") or "")
        if match and condition in CONDITIONS and int(match.group(1)) < len(paragraphs):
            index = int(match.group(1))
            reading.options[str(index)] = {"condition": condition, "end": index, "label": ""}
    out = io.BytesIO()
    document.save(out)
    reading.content = out.getvalue()
    return reading


def _rows(document: Any, paragraphs: list[Any]) -> dict[int, list[int]]:
    """Paragraphe → tous les paragraphes de sa ligne de tableau (lui d'abord)."""
    from docx.oxml.ns import qn

    tree = document.element.getroottree()
    by_row: dict[str, list[int]] = {}
    of: dict[int, str] = {}
    for index, paragraph in enumerate(paragraphs):
        row = paragraph._p
        while row is not None and row.tag != qn("w:tr"):
            row = row.getparent()
        if row is not None:
            path = tree.getpath(row)
            by_row.setdefault(path, []).append(index)
            of[index] = path
    return {i: [i, *(j for j in by_row[p] if j != i)] for i, p in of.items()}


def _spread(paragraphs: list[Any], wanted: dict[int, list[tuple[str, str, str]]],
            protected: list[str]) -> None:  # fmt: skip
    """Un nom, une adresse de la fiche trouvés une fois : remplacés aussi là où l'assistant ne
    les a pas signalés (signature, décharge…) — mots entiers, jamais dans un libellé."""
    found: dict[str, str] = {}
    for items in wanted.values():
        for value, code, _ in items:
            if code in SPREAD and len(value.strip()) >= 4 and not letter.HOLE.fullmatch(value):
                found.setdefault(value, code)
    if not found:
        return
    for index, paragraph in enumerate(paragraphs):
        text = paragraph.text
        have = {value for value, _, _ in wanted.get(index, [])}
        for value, code in found.items():
            if value in have or any(value in p for p in protected):
                continue
            if re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", text):
                wanted.setdefault(index, []).append((value, code, ""))


def overlay(holes: dict[str, dict[str, Any]], content: bytes, kind: str,
            reading: Reading) -> dict[str, dict[str, Any]]:  # fmt: skip
    """Les trous du modèle final, avec ce que l'assistant a compris de ses repères (les règles
    de l'outil ont pu en ajouter d'autres autour, en garde-fou : ils gardent leur réglage)."""
    result = dict(holes)
    by_paragraph: dict[int, list[letter.Hole]] = {}
    for hole in letter.holes(content, kind):
        by_paragraph.setdefault(int(hole.key.split(":")[0]), []).append(hole)
    for index, marks in reading.marks.items():
        pending = list(marks)
        for hole in by_paragraph.get(index, []):
            if not pending:
                break
            marker, code, label = pending[0]
            if hole.text != marker:
                continue
            pending.pop(0)
            entry: dict[str, Any] = {"field": code, "label": label if code == letter.ASK else "",
                                     "source": "assistant"}  # fmt: skip
            before = holes.get(hole.key) or {}
            if code == letter.ASK and not label:
                entry["label"] = before.get("label") or marker.strip("[]")
            if code == letter.ASK and before.get("same"):
                entry["same"] = before["same"]  # même repère qu'un trou plus haut
            result[hole.key] = entry
    return _unique(result)


def _unique(holes: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Deux questions au même intitulé recevraient la même réponse : on les distingue, sauf le
    même repère répété (« same »)."""
    seen: dict[str, int] = {}
    for key in sorted(holes, key=lambda k: tuple(int(p) for p in k.split(":"))):
        value = holes[key]
        if value.get("field") != letter.ASK or value.get("same"):
            continue
        label = value.get("label") or ""
        norm = normalize_text(label)
        seen[norm] = seen.get(norm, 0) + 1
        if label and seen[norm] > 1:
            value["label"] = f"{label} ({seen[norm]})"
    return holes
