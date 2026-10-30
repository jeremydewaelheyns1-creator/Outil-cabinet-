"""PV d'assemblée générale préparé depuis la case « AG » de l'onglet Clôture (D-120).

Le texte est celui d'un modèle Word du cabinet (Paramètres › Modèles de PV d'AG, un ou
plusieurs par forme de société), réglé une fois comme la lettre de mission (D-069) : l'outil
remplit les trous avec la fiche du client, la ligne de l'exercice et les réponses du
formulaire (date, heures, dividende, montants…). Le brouillon part au client pour signature
en ligne ; signé, il est rangé (Archives › Légal) et coche la case AG. Aucune IA.
"""

from __future__ import annotations

import hashlib
from datetime import date, time
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


def prepare(year: ClosingYear, template: Any, answers: dict[str, str], ctx: dict[str, str],
            user: User | None) -> Document:  # fmt: skip
    """Le brouillon du PV (PDF), à relire puis à envoyer pour signature."""
    client = year.client
    content = letter.to_pdf(letter.fill(template, client, answers, ctx), "PV d'assemblée générale")
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
        year.ag_answers = {**answers, **{f"ctx:{k}": v for k, v in ctx.items()}}
        year.save(update_fields=["ag_draft", "ag_answers"])
    deposits.set_dividend(year, ctx["dividende"] == "oui", user)
    events.emit(
        "document.generated", subject=client, actor=user,
        payload={"document": str(document.pk), "type": DOC_TYPE},
    )  # fmt: skip
    return document


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
