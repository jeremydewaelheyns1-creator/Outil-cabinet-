"""Factures du cabinet déposées dans « Déposer des documents » : rangées chez le client (D-105).

Demande de Jeremy : « le patron vient déposer les factures qu'il a générées et le logiciel
détecte automatiquement le dossier et vient la classer dedans ».

Comment, sans IA :
1. une **facture** (ou note de crédit) : le mot est dans le texte du PDF ;
2. **émise par le cabinet** : son nom (Paramètres › Réglages du cabinet) ou son numéro
   d'entreprise y figure ; sans nom ni numéro encodés, rien n'est reconnu ;
3. le **client** : un numéro d'entreprise (ou de TVA) d'un dossier visible, autre que celui
   du cabinet ; sinon le nom d'un seul dossier visible écrit sur la facture. Plusieurs dossiers
   possibles, ou aucun → « À classer », avec la raison ;
4. rangée dans **Factures** du dossier, titre « Facture 2026-041 du 15/10/2026 ».
Les montants ne sont pas lus : la facture est seulement classée.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.db.models import QuerySet

from apps.clients.models import Client
from apps.core.text import normalize_text
from apps.vat import intervat

FOLDER = "factures"
INVOICE = ("facture", "factuur", "invoice")
CREDIT_NOTE = ("note de credit", "creditnota")
NUMBER = re.compile(
    r"(?:facture|factuur|invoice|note\s+de\s+cr[ée]dit|creditnota)\s*"
    r"(?:n[°ºo]\.?|num[ée]ro|nr\.?|no\.?|#)?\s*:?\s*([A-Z0-9][A-Z0-9/._-]{0,24}\d[A-Z0-9/._-]{0,8})",
    re.I,
)
DATE = re.compile(r"(?<!\d)(\d{1,2})[/.-](\d{1,2})[/.-](20\d{2})(?!\d)")
MIN_NAME = 4  # un nom plus court ne suffit pas à reconnaître un dossier


@dataclass
class Found:
    clients: list[Client]
    title: str
    reason: str = ""


def _words(text: str) -> str:
    return f" {re.sub(r'[^a-z0-9]+', ' ', normalize_text(text))} "


def _issued_by_cabinet(text: str, name: str, number: str) -> bool:
    words = _words(text)
    plain_name = _words(name).strip()
    if len(plain_name) >= MIN_NAME and f" {plain_name} " in words:
        return True
    digits = intervat.normalize_number(number or "")
    cited = {intervat.normalize_number(m) for m in intervat.NUMBER.findall(text)}
    return bool(digits) and digits in cited


def _title(text: str, credit: bool) -> str:
    kind = "Note de crédit" if credit else "Facture"
    number = NUMBER.search(text)
    date = DATE.search(text)
    title = kind
    if number:
        title += f" {number.group(1).strip('.-/')}"
    if date:
        day, month, year = (int(g) for g in date.groups())
        title += f" du {day:02d}/{month:02d}/{year}"
    return title


def _by_name(text: str, clients: QuerySet[Client], cabinet: str) -> list[Client]:
    words = _words(text)
    own = _words(cabinet).strip()
    found = []
    for client in clients:
        names = {client.name, client.display_name}
        if client.first_name:
            names |= {f"{client.first_name} {client.name}", f"{client.name} {client.first_name}"}
        for name in names:
            plain = _words(name).strip()
            if len(plain) >= MIN_NAME and plain != own and f" {plain} " in words:
                found.append(client)
                break
    return found


def recognise(text: str, clients: QuerySet[Client], cabinet_name: str,
              cabinet_number: str) -> Found | None:  # fmt: skip
    """Facture émise par le cabinet, et le(s) dossier(s) client trouvé(s) ; None : ce n'est
    pas une facture du cabinet."""
    plain = normalize_text(text)
    credit = any(word in plain for word in CREDIT_NOTE)
    if not credit and not any(word in plain for word in INVOICE):
        return None
    if not _issued_by_cabinet(text, cabinet_name, cabinet_number):
        return None
    title = _title(text, credit)
    own = intervat.normalize_number(cabinet_number or "")
    cited = [intervat.normalize_number(m) for m in intervat.NUMBER.findall(text)]
    numbers = [n for n in dict.fromkeys(cited) if n and n != own]
    if numbers:
        known = {c.enterprise_number: c for c in clients.filter(enterprise_number__in=numbers)}
        first = next((known[n] for n in numbers if n in known), None)
        if first is not None:
            return Found([first], title)
    matches = _by_name(text, clients, cabinet_name)
    if len(matches) == 1:
        return Found(matches, title)
    reason = "plusieurs dossiers correspondent" if matches else "aucun dossier ne correspond"
    return Found(matches, title, reason)
