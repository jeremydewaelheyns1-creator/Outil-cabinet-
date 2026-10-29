"""Nom du cabinet utilisateur de l'outil (D-105)."""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache

CACHE_KEY = "cabinet:nom"


def cabinet_name() -> str:
    """Le nom saisi dans Paramètres › Réglages du cabinet, sinon celui de l'installation."""
    found = cache.get(CACHE_KEY)
    if found is None:
        from .models import CabinetSettings

        found = CabinetSettings.current().name.strip() or str(settings.CABINET_NAME)
        cache.set(CACHE_KEY, found, 300)
    return str(found)


def forget() -> None:
    cache.delete(CACHE_KEY)
