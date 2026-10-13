"""Numéros belges fictifs mais valides (somme de contrôle correcte)."""


def enterprise_number(seed: int) -> str:
    """Numéro d'entreprise valide, différent pour chaque `seed` (0 à 999 999)."""
    base = f"0{200_000 + seed:07d}"
    check = 97 - int(base) % 97
    return f"{base}{check:02d}"


def national_number(seed: int, birth: str = "850730") -> str:
    """Numéro national valide pour une naissance au XXe siècle (format AAMMJJ)."""
    first9 = f"{birth}{seed % 997 + 1:03d}"
    check = 97 - int(first9) % 97
    return f"{first9}{check:02d}"
