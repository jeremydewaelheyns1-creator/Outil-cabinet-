"""L'assistant IA règle un modèle Word (lettre de mission, PV d'AG) : il propose ce que contient
chaque trou et quels passages sont à options (D-121). Le modèle du cabinet ne contient pas de
données de clients ; il est tout de même minimisé (`privacy.mask`). Rien n'est activé : un
administrateur vérifie les propositions, puis enregistre."""

from __future__ import annotations

import json
from typing import Any

from apps.core.models import User
from apps.documents import letter

from . import client, privacy

SYSTEM = (
    "Tu aides un cabinet comptable belge à régler un modèle Word. Pour chaque trou à compléter, "
    "choisis UN code parmi la liste fournie (ce que l'outil doit y mettre). Utilise "
    "« demander » quand c'est une information à taper à chaque document (montant, lieu…) et "
    "donne alors une question courte en français. Indique aussi les paragraphes qui ne "
    "valent que dans certains cas, avec un code de condition de la liste. Réponds uniquement "
    'en JSON : {"trous": {"clé": {"code": "...", "question": "..."}}, '
    '"paragraphes": {"numéro": "condition"}}.'
)


def _prompt(template: Any) -> str:
    content = bytes(template.content)
    holes = [
        {"clé": h.key, "avant": privacy.mask(h.before[-80:]), "trou": privacy.mask(h.text),
         "après": privacy.mask(h.after[:60])}
        for h in letter.holes(content, template.kind)
    ]  # fmt: skip
    paragraphs = [
        {"numéro": i, "texte": privacy.mask(text[:300])} for i, text in letter.paragraphs(content)
    ]
    codes = dict(letter.choices(template.kind))
    conditions = {k: v for k, v in letter.conditions(template.kind).items() if k}
    return json.dumps(
        {"sorte": template.get_kind_display(), "codes": codes, "conditions": conditions,
         "trous": holes, "paragraphes": paragraphs},
        ensure_ascii=False,
    )  # fmt: skip


def suggest(template: Any, user: User | None) -> tuple[int, int]:
    """Applique les propositions au modèle (marquées « assistant ») ; renvoie (trous,
    paragraphes) proposés. Lève `client.Unavailable` si l'assistant ne répond pas."""
    answer = client.ask_json("reglage_modele", SYSTEM, _prompt(template), user=user)
    allowed = {code for code, _ in letter.choices(template.kind)}
    conditions = set(letter.conditions(template.kind)) - {""}
    keys = {h.key for h in letter.holes(bytes(template.content), template.kind)}
    holes = dict(template.holes)
    count_holes = 0
    for key, value in (answer.data.get("trous") or {}).items():
        if key not in keys or not isinstance(value, dict) or value.get("code") not in allowed:
            continue
        label = str(value.get("question") or "")[:120]
        holes[key] = {"field": value["code"], "label": label, "source": "assistant"}
        count_holes += 1
    indexes = {str(i) for i, _ in letter.paragraphs(bytes(template.content))}
    options = dict(template.options)
    count_options = 0
    for index, condition in (answer.data.get("paragraphes") or {}).items():
        if str(index) in indexes and condition in conditions:
            options[str(index)] = {"condition": condition, "end": int(index), "label": ""}
            count_options += 1
    template.holes, template.options = holes, options
    template.save(update_fields=["holes", "options"])
    return count_holes, count_options
