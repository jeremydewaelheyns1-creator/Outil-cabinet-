"""PV d'assemblée générale préparé depuis la case « AG » de l'onglet Clôture (D-120).

Le texte est celui d'un modèle Word du cabinet (Paramètres › Modèles de PV d'AG, un ou
plusieurs par forme de société), réglé une fois comme la lettre de mission (D-069) : l'outil
remplit les trous avec la fiche du client, la ligne de l'exercice et les réponses du
formulaire (date, heures, dividende, montants…). Le brouillon part au client pour signature
en ligne ; signé, il est rangé (Archives › Légal) et coche la case AG. Aucune IA.
"""

from __future__ import annotations

import copy
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.clients.models import Client
from apps.core import events
from apps.core.models import Event, User
from apps.documents import letter
from apps.documents.models import Document, DocumentRequest

from . import deposits
from .models import ClosingYear

MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre")  # fmt: skip
DOC_TYPE = "pv_ag"


def long_date(day: date) -> str:
    return f"{'1er' if day.day == 1 else day.day} {MONTHS[day.month - 1]} {day.year}"


def context(year: ClosingYear, day: date, start: time, end: time, dividend: bool,
            others: str) -> dict[str, str]:  # fmt: skip
    """Ce que le modèle peut reprendre en plus de la fiche (codes `ag.*`, `exercice.*`)."""
    return {
        "date": f"{day:%d/%m/%Y}",
        "date_longue": long_date(day),
        "annee": str(day.year),
        "debut": f"{start:%H:%M}".replace(":", "h"),
        "fin": f"{end:%H:%M}".replace(":", "h"),
        "exercice_debut": f"{year.start:%d/%m/%Y}",
        "exercice_fin": f"{year.end:%d/%m/%Y}",
        "dividende": "oui" if dividend else "non",
        "autres": others,
    }


def uses_others(template: Any) -> bool:
    """Le modèle a-t-il un trou pour des résolutions supplémentaires ?"""
    return any((v or {}).get("field") == "ag.autres" for v in template.holes.values())


def known(client: Client) -> list[tuple[str, str]]:
    """Ce que l'outil remplit tout seul (montré au comptable : « Déjà rempli »)."""
    rows = [
        ("Société", client.display_name),
        ("Siège", ", ".join(client.address_lines)),
        ("Numéro d'entreprise", client.enterprise_number_display or ""),
        ("Président (gérant, administrateur)", letter.FIELDS["client.representant"][1](client)),
        ("Associés", letter.AG_FIELDS["client.associes"][1](client, {})),
    ]
    return [(label, value or "— à compléter dans la fiche") for label, value in rows]


@dataclass(frozen=True)
class Sum:
    """Un tableau de montants du modèle : les lignes signées font la dernière (le total)."""

    total: str  # clé de la question (« trou:31:0 »)
    label: str
    parts: tuple[tuple[str, int], ...]  # (clé, +1 / -1)


def sums(template: Any) -> list[Sum]:
    """Les totaux du modèle, retrouvés dans ses tableaux : chaque montant demandé est une ligne,
    « (-) » dans la ligne la retranche, la dernière ligne est le total des autres."""
    from docx.oxml.ns import qn

    asked = {
        key.rsplit(":", 1)[0]: (key, (value or {}).get("label", ""))
        for key, value in template.holes.items()
        if (value or {}).get("field") == letter.ASK
    }
    tables: dict[Any, list[tuple[str, str, int]]] = {}
    for index, paragraph in enumerate(letter._paragraphs(letter._open(bytes(template.content)))):
        found = asked.get(str(index))
        if found is None:
            continue
        row = paragraph._p
        while row is not None and row.tag != qn("w:tr"):
            row = row.getparent()
        if row is None:
            continue
        text = "".join(t.text or "" for t in row.iter(qn("w:t")))
        sign = -1 if re.search(r"\(\s*-\s*\)", text) else 1
        rows = tables.setdefault(row.getparent(), [])
        if all(r[0] != f"trou:{found[0]}" for r in rows):
            rows.append((f"trou:{found[0]}", found[1], sign))
    result = []
    for rows in tables.values():
        if len(rows) >= 3:
            *parts, (total, label, _) = rows
            result.append(Sum(total, label, tuple((k, sign) for k, _, sign in parts)))
    return result


def _number(text: str) -> Decimal | None:
    cleaned = re.sub(r"[^\d,.-]", "", text or "").replace(".", "").replace(",", ".")
    try:
        return Decimal(cleaned) if cleaned else None
    except InvalidOperation:
        return None


def _money(value: Decimal) -> str:
    whole = f"{abs(value):,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    return ("-" if value < 0 else "") + whole


def check_amounts(template: Any, answers: dict[str, str]) -> list[str]:
    """Ce qui ne colle pas dans les montants tapés (le total d'un tableau, le bénéfice reporté).
    Un avertissement : le comptable peut confirmer s'il a une raison."""
    problems = []
    labels = {key: label for key, label in letter.questions(template)}
    totals: dict[str, Decimal] = {}
    for block in sums(template):
        values = [(_number(answers.get(k, "")), sign) for k, sign in block.parts]
        total = _number(answers.get(block.total, ""))
        if total is None or any(v is None for v, _ in values):
            continue
        computed = sum((v * sign for v, sign in values if v is not None), Decimal(0))
        totals[block.label.lower()] = total
        if computed != total:
            problems.append(f"« {block.label} » vaut {_money(total)}, mais les lignes au-dessus "
                            f"donnent {_money(computed)}")  # fmt: skip
    net = next((v for label, v in totals.items() if "net" in label or "affecter" in label), None)
    for key, label in labels.items():
        low = label.lower()
        value = _number(answers.get(key, ""))
        if net is None or value is None or "intégralité" not in low:
            continue
        if value != net:
            problems.append(f"« {label} » ({_money(value)}) devrait être le bénéfice net "
                            f"({_money(net)})")  # fmt: skip
    return problems


RESOLUTION = re.compile(r"^\s*Résolution\s+(\d+)\s*:?\s*$", re.I)
END = re.compile(r"toutes ces résolutions|séance est levée|ordre du jour étant", re.I)


def add_resolution(word: bytes, text: str) -> bytes:
    """Ajoute au PV ce que le comptable a écrit dans « Autre chose ? » : une résolution de plus
    (« Résolution 7 : »), dans la mise en forme des précédentes, avant la clôture de séance."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return word
    document = letter._open(word)
    paragraphs = [p for p in document.paragraphs]
    heads = [(i, int(m.group(1))) for i, p in enumerate(paragraphs)
             if (m := RESOLUTION.match(p.text))]  # fmt: skip
    end = next((i for i, p in enumerate(paragraphs)
                if END.search(p.text) and (not heads or i > heads[-1][0])), None)  # fmt: skip
    if end is None:
        return word
    anchor = paragraphs[end]._p
    if heads:
        head_index, number = heads[-1]
        head_model = paragraphs[head_index]._p
        body_model = paragraphs[head_index + 1]._p
        new_head = _copy_paragraph(head_model, f"Résolution {number + 1} :")
        anchor.addprevious(new_head)
    else:
        body_model = paragraphs[end - 1]._p if end else anchor
    for line in lines:
        anchor.addprevious(_copy_paragraph(body_model, line))
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def _copy_paragraph(model: Any, text: str) -> Any:
    """Un paragraphe comme `model` (style, retrait, police du premier passage) avec `text`."""
    from docx.oxml.ns import qn

    clone = copy.deepcopy(model)
    runs = clone.findall(qn("w:r"))
    for child in list(clone):
        if child.tag != qn("w:pPr") and child is not (runs[0] if runs else None):
            clone.remove(child)
    if runs:
        run = runs[0]
        for child in list(run):
            if child.tag != qn("w:rPr"):
                run.remove(child)
    else:
        from docx.oxml import OxmlElement

        run = OxmlElement("w:r")
        clone.append(run)
    from docx.oxml import OxmlElement

    t = OxmlElement("w:t")
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text
    run.append(t)
    return clone


def build(template: Any, client: Client, answers: dict[str, str], ctx: dict[str, str]) -> bytes:
    """Le PV rempli (Word) : le modèle, et « Autre chose ? » en résolution de plus quand le
    modèle n'a pas de trou prévu pour ça."""
    content = letter.fill(template, client, answers, ctx)
    if ctx.get("autres") and not uses_others(template):
        content = add_resolution(content, ctx["autres"])
    return content


def prepare(year: ClosingYear, template: Any, answers: dict[str, str], ctx: dict[str, str],
            user: User | None) -> Document:  # fmt: skip
    """Le brouillon du PV (PDF), à relire puis à envoyer pour signature."""
    client = year.client
    content = letter.to_pdf(build(template, client, answers, ctx), "PV d'assemblée générale")
    with transaction.atomic():
        old = year.ag_draft
        if old is not None and old.state == Document.State.DRAFT:
            old.file.delete(save=False)
            old.delete()
        document = Document(
            client=client,
            title=f"PV d'AG {year.label} ({ctx['date']})",
            folder="legal",
            doc_type=DOC_TYPE,
            source=Document.Source.UPLOAD,
            generated=True,
            state=Document.State.DRAFT,
            original_name=f"pv_ag_{year.label}.pdf",
            content_type="application/pdf",
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            uploaded_by=user,
        )
        document.file.save("document", ContentFile(content), save=False)
        document.save()
        year.ag_draft = document
        year.ag_answers = {**answers, **{f"ctx:{k}": v for k, v in ctx.items()},
                           "modele": template.pk}  # fmt: skip
        year.save(update_fields=["ag_draft", "ag_answers"])
    deposits.set_dividend(year, ctx["dividende"] == "oui", user)
    events.emit(
        "document.generated", subject=client, actor=user,
        payload={"document": str(document.pk), "type": DOC_TYPE},
    )  # fmt: skip
    return document


def word(year: ClosingYear) -> bytes | None:
    """Le PV rempli en Word (typographie exacte du modèle), refait depuis les réponses gardées."""
    from apps.documents.models import LetterTemplate

    saved = year.ag_answers or {}
    template = LetterTemplate.objects.filter(pk=saved.get("modele") or 0).first()
    if template is None or year.ag_draft_id is None:
        return None
    answers = {k: v for k, v in saved.items() if k.startswith(("trou:", "option:"))}
    ctx = {k[4:]: v for k, v in saved.items() if k.startswith("ctx:")}
    return build(template, year.client, answers, ctx)


def waiting_signature(year: ClosingYear) -> bool:
    draft = year.ag_draft
    return draft is not None and draft.state == Document.State.AWAITING_SIGNATURE


@events.on("document.signed")
def signed(event: Event) -> None:
    """PV d'AG signé par le client : il rejoint la case AG de son exercice, qui se coche."""
    payload = event.payload or {}
    request = DocumentRequest.objects.filter(reference=payload.get("demande", "")).first()
    if request is None or request.doc_type != DOC_TYPE:
        return
    year = ClosingYear.objects.filter(ag_draft__request=request).first()
    signed_doc = Document.objects.filter(pk=str(payload.get("document") or "")).first()
    if year is None or signed_doc is None:
        return
    if not year.deposits.filter(kind=deposits.Kind.AG, documents=signed_doc).exists():
        deposits.attach(year, deposits.Kind.AG, signed_doc, None)


def today() -> date:
    return timezone.localdate()
