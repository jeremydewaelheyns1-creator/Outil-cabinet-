"""Écran de la fiche de risque guidée (D-049)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from apps.clients.models import Client
from apps.clients.views import _get_client, render_section
from apps.core.audit import log_access
from apps.core.capabilities import Capability
from apps.core.http import AppRequest
from apps.core.models import AccessLog
from apps.core.permissions import require_capability

from . import risk
from .models import RiskAssessment


def risk_sheet(request: AppRequest, pk: int) -> HttpResponse:
    """Questionnaire pré-rempli ; à l'envoi : niveau, prochaine révision, PDF rangé."""
    if request.method == "POST":
        if not request.user.has_capability(Capability.CLIENTS_EDIT):
            raise Http404
        client = _get_client(request, pk)
        answers = {q.key: request.POST.get(q.key) == "oui" for q in risk.QUESTIONS}
        missing = [q for q in risk.QUESTIONS if request.POST.get(q.key) not in {"oui", "non"}]
        if missing:
            messages.error(request, "Répondez à toutes les questions (oui ou non).")
        else:
            assessment = risk.save(
                client, answers, user=request.user, comment=request.POST.get("commentaire", "")
            )
            log_access(request, AccessLog.Action.CREATE, client, details={"fiche de risque": 1})
            text = (
                f"Fiche enregistrée : risque {assessment.get_level_display().lower()}, "
                f"prochaine révision le {assessment.next_review:%d/%m/%Y}."
            )
            if assessment.awaiting_approval:
                text += " Elle attend la validation de l'AMLCO."
            messages.success(request, text)
            return redirect("clients:document_case", pk=client.pk, slug="fiche-risque")

    def build(client: Client) -> dict[str, Any]:
        proposals = risk.propose(client)
        posted = request.POST if request.method == "POST" else None
        return {
            "proposals": [
                (
                    p,
                    posted.get(p.question.key)
                    if posted
                    else ("oui" if p.answer else "non" if p.answer is False else ""),
                )
                for p in proposals
            ],
            "history": client.risk_assessments.select_related("created_by", "approved_by")[:10],
            "can_decide": request.user.has_capability(Capability.AML_DECIDE),
            "review_years": settings.RISK_REVIEW_YEARS,
        }

    return render_section(request, pk, "documents:fiche-risque", "documents/risk_sheet.html", build)


@require_POST
@require_capability(Capability.AML_DECIDE)
def risk_approve(request: AppRequest, pk: int, assessment_id: int) -> HttpResponse:
    client = _get_client(request, pk)
    assessment = get_object_or_404(RiskAssessment, pk=assessment_id, client=client)
    if assessment.awaiting_approval:
        risk.approve(assessment, request.user)
        log_access(request, AccessLog.Action.UPDATE, client, details={"risque validé": 1})
        messages.success(request, "Risque élevé validé : la relation peut être acceptée.")
    return redirect("clients:document_case", pk=client.pk, slug="fiche-risque")
