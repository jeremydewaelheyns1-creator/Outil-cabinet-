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


def _posted(request: AppRequest) -> dict[str, dict[str, str]]:
    return {
        q.key: {"level": request.POST.get(q.key, ""), "comment": request.POST.get(f"{q.key}-c", "")}
        for q in risk.QUESTIONS
    }


def risk_sheet(request: AppRequest, pk: int) -> HttpResponse:
    """Grille du modèle ITAA 5.1 pré-remplie ; à l'envoi : synthèse, révision, PDF rangé."""
    fill_low = request.method == "POST" and "remplir" in request.POST
    if request.method == "POST":
        if not request.user.has_capability(Capability.CLIENTS_EDIT):
            raise Http404
        client = _get_client(request, pk)
        if not fill_low:
            answers = _posted(request)
            synthesis = request.POST.get("synthese", "")
            comment = request.POST.get("commentaire", "")
            problems = risk.check(answers, synthesis, comment)
            if problems:
                for problem in problems:
                    messages.error(request, problem)
            else:
                assessment = risk.save(
                    client, answers, user=request.user, synthesis=synthesis, comment=comment
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
        if request.method == "POST":
            values = _posted(request)
            if fill_low:  # « Le reste en faible » : rien n'est enregistré, la grille revient
                for value in values.values():
                    value["level"] = value["level"] or risk.LOW
        else:
            values = {p.question.key: {"level": p.answer or "", "comment": p.comment}
                      for p in proposals}  # fmt: skip
        known = {k: v for k, v in values.items() if v["level"] in risk.ORDER}
        proposed = risk.evaluate(known)[1]
        synthesis = request.POST.get("synthese", "") if not fill_low else ""
        return {
            "rows": [(p, values[p.question.key]) for p in proposals],
            "open_count": sum(1 for v in values.values() if v["level"] not in risk.ORDER),
            "proposed": proposed,
            "synthesis": synthesis or proposed,
            "levels": risk.Level.choices,
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
    # L'AMLCO peut signer toute fiche ; c'est obligatoire pour un risque élevé (D-103).
    if assessment.approved_at is None:
        risk.approve(assessment, request.user)
        log_access(request, AccessLog.Action.UPDATE, client, details={"risque validé": 1})
        high = assessment.level == "high"
        messages.success(request, "Risque élevé validé : la relation peut être acceptée."
                         if high else "Fiche signée par l'AMLCO.")  # fmt: skip
    return redirect("clients:document_case", pk=client.pk, slug="fiche-risque")
