"""Minimisation avant envoi à l'assistant IA (D-121) : les identifiants deviennent des
repères. Le numéro national n'est jamais envoyé."""

from __future__ import annotations

import re

PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[0-9A-Z]{4}){2,7}\s?[0-9A-Z]{1,4}\b"), "[IBAN]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[E-MAIL]"),
    (re.compile(r"(?<!\d)\d{2}[.\s]?\d{2}[.\s]?\d{2}[-.\s]?\d{3}[.\s]?\d{2}(?!\d)"), "[NUMÉRO]"),
    (re.compile(r"\b(?:BE\s?)?[01]\d{3}[.\s]?\d{3}[.\s]?\d{3}\b"), "[NUMÉRO D'ENTREPRISE]"),
]


def mask(text: str) -> str:
    for pattern, marker in PATTERNS:
        text = pattern.sub(marker, text)
    return text
