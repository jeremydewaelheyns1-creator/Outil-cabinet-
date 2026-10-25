"""Que contient cette pièce jointe ? (D-060) — lecture sur le serveur, sans IA.

On réutilise ce que le dépôt unique sait déjà lire (D-041) : déclarations Intervat (XML/PDF),
cartes d'identité (lignes codées lues par Tesseract). Le reste est reconnu par quelques mots
du PDF. Le numéro national lu sur une carte ne sert qu'à retrouver la personne : il n'est ni
gardé, ni affiché, ni journalisé.
"""

from __future__ import annotations

import contextlib

from django.db.models import QuerySet

from apps.clients.models import Client
from apps.documents import identity, mrz
from apps.vat import intervat

from .models import MailAttachment

Kind = MailAttachment.Kind
IMAGES = ("image/jpeg", "image/png")


def _card(content: bytes, content_type: str, clients: QuerySet[Client]) -> str | None:
    text = identity.CARD_READER(content, content_type)
    result = mrz.read(text) if text else None
    del text
    if result is None or not result.valid or not result.document_code.startswith("I"):
        return None
    person = clients.filter(kind=Client.Kind.PERSON, national_number=result.national_number).first()
    return f"Carte d'identité de {person.display_name}" if person else "Carte d'identité"


def recognize(
    name: str, content: bytes, content_type: str, clients: QuerySet[Client]
) -> tuple[str, str]:
    """(sorte, description courte) d'une pièce jointe."""
    lowered_name = name.lower()
    if content_type in ("application/xml", "text/xml") or lowered_name.endswith(".xml"):
        declarations: list[intervat.Declaration] = []
        # Fichier XML quelconque : simplement pas une déclaration Intervat.
        with contextlib.suppress(ValueError, SyntaxError, KeyError, AttributeError, TypeError):
            declarations = list(intervat.parse_xml(content))
        if declarations and declarations[0].kind == intervat.IC:
            return Kind.VAT, "Listing intracommunautaire (fichier Intervat)"
        if declarations:
            return Kind.VAT, "Déclaration TVA (fichier Intervat)"
        return Kind.OTHER, "Fichier XML"
    if content_type == "application/pdf":
        text = intervat.pdf_text(content).lower()
        if intervat.read_pdf(content).looks_like_vat:
            return Kind.VAT, "Déclaration TVA"
        if "registre ubo" in text or "bénéficiaires effectifs" in text or "uiteindelijke" in text:
            return Kind.UBO, "Extrait du registre UBO"
        if "avertissement-extrait de rôle" in text or "aanslagbiljet" in text:
            return Kind.TAX, "Avertissement-extrait de rôle"
        if "facture" in text or "factuur" in text or "invoice" in text:
            return Kind.INVOICE, "Facture"
    if content_type in IMAGES or content_type == "application/pdf":
        card = _card(content, content_type, clients)
        if card:
            return Kind.CARD, card
    if content_type in IMAGES:
        return Kind.OTHER, "Photo"
    if content_type == "application/pdf":
        return Kind.OTHER, "Document PDF"
    return Kind.OTHER, "Fichier"
