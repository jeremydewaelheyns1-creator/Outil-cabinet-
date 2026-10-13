"""Dossier actif, disponible dans tous les gabarits (barre du haut, menu du dossier)."""

from typing import Any

from django.http import HttpRequest

from . import dossier


def current_dossier(request: HttpRequest) -> dict[str, Any]:
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    client = dossier.current(request)
    return {
        "current_client": client,
        "dossier_sections": dossier.sections_for(client) if client else [],
        "dossier_upcoming": dossier.UPCOMING if client else (),
        "current_section": dossier.section_of(request),
    }
