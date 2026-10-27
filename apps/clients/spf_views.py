"""Encadré « Mandats SPF » de la page Documents du dossier (D-072)."""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core import events
from apps.core.audit import log_access
from apps.core.capabilities import Capability
from apps.core.http import AppRequest
from apps.core.models import AccessLog
from apps.core.permissions import require_capability

from . import spf
from .models import SpfMandate
from .views import _get_client


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def spf_mandate_update(request: AppRequest, pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    kind, status = request.POST.get("kind", ""), request.POST.get("status", "")
    if kind not in spf.needed(client) or status not in SpfMandate.Status.values:
        messages.error(request, "Changement refusé.")
        return redirect("clients:documents", pk=client.pk)
    SpfMandate.objects.update_or_create(
        client=client,
        kind=kind,
        defaults={"status": status, "updated_at": timezone.now(), "updated_by": request.user},
    )
    log_access(request, AccessLog.Action.UPDATE, client,
               details={"mandat SPF": kind, "état": status})  # fmt: skip
    events.emit("spf_mandate.changed", subject=client, actor=request.user,
                payload={"mandat": kind, "etat": status})  # fmt: skip
    return redirect("clients:documents", pk=client.pk)
