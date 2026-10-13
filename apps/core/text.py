"""Petits outils de texte partagés (recherche, comparaison, correspondance d'en-têtes)."""

import re
import unicodedata

_SPACES = re.compile(r"\s+")
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'"})


def strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_text(value: str | None) -> str:
    """« Société  Générale » → « societe generale » : pour comparer et rechercher."""
    if not value:
        return ""
    value = strip_accents(str(value).translate(_APOSTROPHES)).lower()
    return _SPACES.sub(" ", value).strip()


def normalize_key(value: str | None) -> str:
    """« N° d'entreprise : » → « n d entreprise » : pour faire correspondre des en-têtes."""
    value = normalize_text(value).replace("°", " ").replace("º", " ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return _SPACES.sub(" ", value).strip()
