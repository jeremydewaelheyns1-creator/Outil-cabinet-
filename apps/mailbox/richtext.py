"""Mise en forme des e-mails écrits dans l'outil : gras, italique, souligné, listes.

L'éditeur du navigateur produit du HTML ; seules quelques balises de mise en forme sont
gardées (aucun attribut, aucun lien, aucune image, aucun script) avant l'envoi par Outlook.
Sans JavaScript, le texte brut du formulaire est envoyé, avec ses retours à la ligne.
"""

from __future__ import annotations

import html
import re

import nh3
from django.utils.html import escape, linebreaks

TAGS = {"p", "br", "div", "strong", "b", "em", "i", "u", "ul", "ol", "li"}
MAX_LENGTH = 100_000
_BLOCK = re.compile(r"</(p|div|li)>|<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


def clean(raw: str) -> str:
    """HTML sûr : seules les balises de mise en forme restent."""
    return nh3.clean(raw[:MAX_LENGTH], tags=TAGS, attributes={}).strip()


def to_text(safe_html: str) -> str:
    """Le même message en texte simple (contrôle « message vide », copie de recherche)."""
    text = _TAG.sub("", _BLOCK.sub("\n", safe_html))
    return re.sub(r"\n{3,}", "\n\n", html.unescape(text)).strip()


def body(html_field: str, text_field: str) -> tuple[str, str]:
    """(HTML à envoyer, texte simple) à partir de l'éditeur, ou du texte brut sans JavaScript."""
    safe = clean(html_field or "")
    text = to_text(safe)
    if text:
        return safe, text
    text = (text_field or "").strip()[:MAX_LENGTH]
    return (linebreaks(escape(text)) if text else ""), text


SIGNATURE_MAX = 5_000


def with_signature(message_html: str, signature_html: str) -> str:
    """Le message suivi de la signature (déjà nettoyée), séparés par une ligne vide."""
    if not signature_html or not to_text(signature_html):
        return message_html
    return f"{message_html}<br><div>{signature_html}</div>"
