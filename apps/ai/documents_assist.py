"""L'assistant IA lit un document que les règles n'ont pas reconnu (« À classer ») et propose
où le ranger (D-121). L'outil, lui, retrouve le dossier : par les numéros imprimés (règles
habituelles), sinon par le nom proposé, parmi les dossiers visibles de la personne. Rien
n'est rangé sans son clic. Les documents des clients ne partent vers l'assistant que si le
cabinet a confirmé le « zéro conservation » (Réglages du cabinet), et masqués."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet

from apps.clients import dossier
from apps.clients.models import Client
from apps.core.models import User
from apps.documents import inbox, spf_docs
from apps.documents.models import InboxItem
from apps.vat import intervat

from . import client as ai
from . import privacy

MAX_TEXT = 6000
SYSTEM = (
    "Tu aides un cabinet comptable belge à classer un document reçu. Dis de quoi il s'agit "
    "(titre court en français, avec l'année concernée si elle est écrite), dans quel dossier "
    "d'archives il va (un code de la liste), et le nom de la société ou de la personne qu'il "
    "concerne tel qu'il est écrit. Si tu n'es pas sûr, mets null. Réponds uniquement en JSON : "
    '{"titre": "...", "dossier": "code", "nom": "..."}'
)


def _cited(text: str, clients: QuerySet[Client]) -> Client | None:
    """Le dossier par les numéros imprimés (comme les règles) : entreprise, puis national."""
    from apps.core.models import CabinetSettings

    cabinet = intervat.normalize_number(CabinetSettings.current().enterprise_number or "")
    cited = (intervat.normalize_number(m) for m in intervat.NUMBER.findall(text))
    ordered = [n for n in dict.fromkeys(cited) if n and n != cabinet]
    if ordered:
        known = {c.enterprise_number: c for c in clients.filter(enterprise_number__in=ordered)}
        first = next((known[n] for n in ordered if n in known), None)
        if first is not None:
            return first
    nationals = spf_docs._national_numbers(text)
    if nationals:
        persons = list(clients.filter(kind=Client.Kind.PERSON, national_number__in=nationals)[:2])
        if len(persons) == 1:
            return persons[0]
    return None


def _by_name(name: str, clients: QuerySet[Client]) -> Client | None:
    words = [w for w in name.replace(",", " ").split() if len(w) > 2][:3]
    if not words:
        return None
    found = clients
    for word in words:
        found = found.filter(name__icontains=word)
    matches = list(found[:2])
    return matches[0] if len(matches) == 1 else None


def suggest(item: InboxItem, clients: QuerySet[Client], user: User) -> dict[str, Any]:
    """Demande une proposition et la garde sur l'élément « À classer ». Lève
    `ai.Unavailable` si l'assistant ne peut pas répondre."""
    item.file.open("rb")
    try:
        content = item.file.read()
    finally:
        item.file.close()
    text = spf_docs.text_of(content)
    if not text.strip():
        raise ai.Unavailable("Aucun texte lisible dans ce document.")
    folders = {slug: s.label for slug, s in dossier.DOCUMENT_FOLDERS.items()}
    prompt = (
        f"Dossiers d'archives possibles : {folders}\n\nDocument :\n{privacy.mask(text[:MAX_TEXT])}"
    )
    answer = ai.ask_json("classement_document", SYSTEM, prompt, user=user, personal=True,
                         model="mistral-small-latest")  # fmt: skip
    client = _cited(text, clients) or _by_name(str(answer.data.get("nom") or ""), clients)
    folder = str(answer.data.get("dossier") or "")
    place = f"folder:{folder}"
    title = str(answer.data.get("titre") or "")[:200]
    proposal: dict[str, Any] = {"title": title or item.original_name}
    if client is not None:
        allowed = {value for value, _ in inbox.places(client)}
        proposal["client"] = client.pk
        proposal["client_name"] = client.display_name
        if place in allowed:
            proposal["place"] = place
            proposal["place_label"] = dict(inbox.places(client))[place]
    answer.call.client = client
    answer.call.save(update_fields=["client"])
    item.suggestion = proposal
    item.save(update_fields=["suggestion"])
    return proposal
