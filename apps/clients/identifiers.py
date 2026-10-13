"""Numéros belges : normalisation, contrôle et mise en forme.

On s'appuie sur python-stdnum (bibliothèque éprouvée) pour les sommes de contrôle, et on
stocke toujours la forme compacte (chiffres seuls) ; la mise en forme sert à l'affichage.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from stdnum.be import nn, vat
from stdnum.exceptions import ValidationError as StdnumError


def normalize_enterprise_number(value: str | None) -> str:
    """'BE 0403.170.701' → '0403170701'. Lève ValidationError si le numéro est invalide."""
    if value is None or not str(value).strip():
        return ""
    try:
        return str(vat.validate(str(value)))
    except StdnumError as exc:
        raise ValidationError(
            "Numéro d'entreprise invalide : %(value)s", params={"value": value}
        ) from exc


def format_enterprise_number(value: str) -> str:
    """'0403170701' → '0403.170.701'."""
    if len(value) != 10:
        return value
    return f"{value[:4]}.{value[4:7]}.{value[7:]}"


def vat_number_from_enterprise_number(value: str) -> str:
    """En Belgique, le numéro de TVA est le numéro d'entreprise précédé de BE."""
    return f"BE{value}" if value else ""


def normalize_national_number(value: str | None) -> str:
    """'AA.MM.JJ-SSS.CC' → 'AAMMJJSSSCC'. Lève ValidationError si le numéro est invalide."""
    if value is None or not str(value).strip():
        return ""
    try:
        return str(nn.validate(str(value)))
    except StdnumError as exc:
        raise ValidationError("Numéro national invalide.") from exc


def format_national_number(value: str) -> str:
    return str(nn.format(value)) if value else ""


def mask_national_number(value: str) -> str:
    """Affichage par défaut : seule la date de naissance reste lisible."""
    if len(value) != 11:
        return "•••" if value else ""
    return f"{value[:2]}.{value[2:4]}.{value[4:6]}-•••.••"


def validate_enterprise_number(value: str) -> None:
    normalize_enterprise_number(value)


def validate_national_number(value: str) -> None:
    normalize_national_number(value)
