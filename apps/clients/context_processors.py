"""Dossier actif, disponible dans tous les gabarits (barre du haut, onglets du dossier)."""

from typing import Any

from django.http import HttpRequest

from . import dossier


def current_dossier(request: HttpRequest) -> dict[str, Any]:
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    client = dossier.current(request)
    section = dossier.section_of(request)
    tabs = dossier.tabs_for(client) if client else []
    current_tab = dossier.TAB_OF.get(section, "")
    return {
        "current_client": client,
        "current_section": section,
        "dossier_tabs": tabs,
        "current_tab": next((t for t in tabs if t.key == current_tab), None),
        "dossier_overdue": _overdue(client) if client else 0,
    }


def _overdue(client: object) -> int:
    from apps.tasks.models import Task  # le module échéances dépend des clients

    return Task.objects.filter(client=client).overdue().count()
