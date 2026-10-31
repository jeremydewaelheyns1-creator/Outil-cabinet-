"""« Quelque chose de particulier ? » du PV d'AG (D-128) : l'assistant comprend la demande du
comptable, trouve où elle va dans le PV et modifie le texte en conséquence (en style de PV,
pas recopiée mot pour mot). Il signale ce qui ne colle pas avec les montants du PV.

Sécurité : le PV rempli contient des données du client ; il ne part que si le cabinet l'a
autorisé (zéro conservation, `personal=True`), numéros et e-mails masqués. Rien n'est
envoyé au client : le comptable relit le brouillon avant l'envoi pour signature."""

from __future__ import annotations

import json
from typing import Any

from apps.clients.models import Client
from apps.core.models import User
from apps.documents import letter

from . import client as ai
from . import privacy

MODEL = "mistral-large-latest"  # rédaction juridique : le modèle le plus soigné

SYSTEM = (
    "Tu es le rédacteur juridique d'un cabinet comptable belge. On te donne un procès-verbal "
    "d'assemblée générale (paragraphes numérotés) et une demande du comptable. Intègre la "
    "demande dans le PV comme un juriste le ferait :\n"
    "- comprends ce qui est décidé et trouve l'endroit où cela se place (affectation du "
    "résultat, rémunération, décharge, nominations, résolution nouvelle avant la levée de "
    "séance…) ;\n"
    "- modifie les paragraphes concernés pour que tout le PV reste cohérent (par ex. un "
    "dividende décidé remplace « reporter l'intégralité du bénéfice » par la répartition : "
    "dividende, report, réserves) ;\n"
    "- écris dans le style formel du PV, à la troisième personne (« L'assemblée décide… »), "
    "jamais la demande recopiée telle quelle ; corrige l'orthographe ;\n"
    "- écris les montants comme dans le PV : 50.000,00 € ;\n"
    "- ne change rien d'autre ; garde la numérotation des résolutions (une nouvelle résolution "
    "prend le numéro suivant) ;\n"
    "- n'invente aucun montant ni nom. Si la demande ne colle pas avec les montants du PV (par "
    "ex. dividende + report > bénéfice à affecter, sans prélèvement sur les réserves), "
    "n'arrange rien : explique-le dans « remarques », en une phrase simple.\n"
    'Réponds uniquement en JSON : {"modifications": [{"paragraphe": n, "action": '
    '"remplacer" | "ajouter_apres" | "supprimer", "texte": "..."}], "remarques": ["..."]}. '
    "Pour plusieurs paragraphes ajoutés au même endroit, donne-les dans l'ordre."
)
ACTIONS = {"remplacer", "ajouter_apres", "supprimer"}


def paragraphs(word: bytes) -> list[tuple[int, str]]:
    return [(i, t) for i, t in letter.paragraphs(word)]


def plan(word: bytes, request_text: str, client: Client, user: User | None
         ) -> tuple[list[dict[str, Any]], list[str]]:  # fmt: skip
    """Les modifications à faire au PV, et les remarques. Lève `ai.Unavailable`."""
    numbered = [{"n": i, "texte": privacy.mask(t[:1500])} for i, t in paragraphs(word)]
    prompt = json.dumps(
        {"pv": numbered, "demande": privacy.mask(request_text[:2000])}, ensure_ascii=False
    )
    answer = ai.ask_json("pv_particulier", SYSTEM, prompt, client=client, user=user,
                         personal=True, model=MODEL)  # fmt: skip
    known = {i for i, _ in paragraphs(word)}
    edits: list[dict[str, Any]] = []
    for item in (answer.data.get("modifications") or [])[:20]:
        if not isinstance(item, dict):
            continue
        number, action = item.get("paragraphe"), item.get("action")
        text = str(item.get("texte") or "").strip()[:2000]
        if not isinstance(number, int) or number not in known or action not in ACTIONS:
            continue
        if action != "supprimer" and not text:
            continue
        edits.append({"paragraphe": number, "action": action, "texte": text})
    remarks = [str(r)[:300] for r in (answer.data.get("remarques") or []) if str(r).strip()][:5]
    if not edits and not remarks:
        raise ai.Unavailable("Réponse vide de l'assistant.")
    return edits, remarks
