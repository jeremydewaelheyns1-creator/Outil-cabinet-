"""Écrans de la lettre de mission sur le modèle du cabinet (D-069).

- Réglages (administrateurs) : déposer le modèle Word, dire ce que contient chaque trou,
  choisir les paragraphes à options, confirmer les éléments obligatoires, activer.
- Dossier : « Préparer la lettre » demande seulement ce que l'outil ne connaît pas
  (honoraires, lieu…), puis produit le brouillon à relire et à envoyer pour signature.
"""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.clients.views import _get_client, render_section
from apps.core.audit import log_access
from apps.core.capabilities import Capability
from apps.core.http import AppRequest
from apps.core.models import AccessLog
from apps.core.permissions import require_capability

from . import letter
from .models import LetterTemplate


def _admin(request: AppRequest) -> None:
    if not request.user.is_staff:
        raise PermissionDenied


def models_page(request: AppRequest) -> HttpResponse:
    """Liste des modèles déposés et dépôt d'un nouveau."""
    _admin(request)
    if request.method == "POST":
        upload = request.FILES.get("modele")
        if upload is None:
            messages.error(request, "Choisissez le fichier Word du modèle.")
            return redirect("lettre:models")
        content = upload.read()
        try:
            letter.check_upload(upload.name or "", content)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("lettre:models")
        found = letter.holes(content)
        template = LetterTemplate.objects.create(
            name=(upload.name or "modele.docx")[:200],
            content=content,
            holes={h.key: {"field": h.guess, "label": h.question} for h in found if h.guess},
            uploaded_by=request.user,
        )
        log_access(request, AccessLog.Action.IMPORT, template, details={"modèle": "lettre"})
        messages.success(
            request,
            f"Modèle déposé : {len(found)} trou(s) repéré(s). Vérifiez ce que l'outil propose.",
        )
        return redirect("lettre:model", template.pk)
    templates = LetterTemplate.objects.select_related("uploaded_by")
    return render(request, "documents/lettre/modeles.html", {"templates": templates})


def model_page(request: AppRequest, template_id: int) -> HttpResponse:
    """Réglage d'un modèle : trous, paragraphes à options, éléments obligatoires."""
    _admin(request)
    template = get_object_or_404(LetterTemplate, pk=template_id)
    content = bytes(template.content)
    if request.method == "POST":
        action = request.POST.get("action", "enregistrer")
        if action == "supprimer":
            log_access(request, AccessLog.Action.DELETE, template, details={"modèle": "lettre"})
            template.delete()
            messages.success(request, "Modèle supprimé.")
            return redirect("lettre:models")
        _save(request, template, content)
        if action == "activer":
            missing = letter.problems(template)
            if missing:
                messages.error(request, "Pas encore utilisable : " + " ; ".join(missing) + ".")
            else:
                with transaction.atomic():
                    LetterTemplate.objects.exclude(pk=template.pk).update(active=False)
                    template.active = True
                    template.save(update_fields=["active"])
                messages.success(request, "Modèle activé : il sert pour les nouvelles lettres.")
        elif action == "desactiver":
            template.active = False
            template.save(update_fields=["active"])
            messages.success(request, "Modèle désactivé.")
        else:
            messages.success(request, "Réglages du modèle enregistrés.")
        log_access(request, AccessLog.Action.UPDATE, template, details={"modèle": action})
        return redirect("lettre:model", template.pk)
    holes = [
        {
            "hole": h,
            "field": (template.holes.get(h.key) or {}).get("field", ""),
            "label": (template.holes.get(h.key) or {}).get("label", ""),
        }
        for h in letter.holes(content)
    ]
    paragraphs = [
        {
            "index": i,
            "text": text,
            "condition": (template.options.get(str(i)) or {}).get("condition", ""),
            "label": (template.options.get(str(i)) or {}).get("label", ""),
        }
        for i, text in letter.paragraphs(content)
    ]
    context = {
        "template": template,
        "holes": holes,
        "paragraphs": paragraphs,
        "checks": letter.checks(content, template.holes),
        "problems": letter.problems(template),
        "choices": letter.CHOICES,
        "conditions": list(letter.CONDITIONS.items()),
        "ask": letter.ASK,
    }
    return render(request, "documents/lettre/modele.html", context)


def _save(request: AppRequest, template: LetterTemplate, content: bytes) -> None:
    allowed = {code for code, _ in letter.CHOICES}
    holes = {}
    for hole in letter.holes(content):
        field = request.POST.get(f"trou-{hole.key}", "")
        if field in allowed:
            label = request.POST.get(f"libelle-{hole.key}", "").strip()[:120]
            holes[hole.key] = {"field": field, "label": label}
    options = {}
    for index, _ in letter.paragraphs(content):
        condition = request.POST.get(f"option-{index}", "")
        if condition and condition in letter.CONDITIONS:
            label = request.POST.get(f"question-{index}", "").strip()[:160]
            options[str(index)] = {"condition": condition, "end": index, "label": label}
    found = {c.code for c in letter.checks(content, holes) if c.excerpt}
    template.holes = holes
    template.options = options
    template.checks = [code for code in request.POST.getlist("verifie") if code in found]
    template.save(update_fields=["holes", "options", "checks"])
    if template.active and letter.problems(template):
        template.active = False
        template.save(update_fields=["active"])
        messages.warning(request, "Le modèle n'est plus complet : il a été désactivé.")


@require_capability(Capability.CLIENTS_EDIT)
def prepare(request: AppRequest, pk: int) -> HttpResponse:
    """Dossier : ce qu'il faut donner pour cette lettre, puis le brouillon à relire."""
    from . import generation

    client = _get_client(request, pk)
    template = letter.active()
    questions = letter.questions(template) if template is not None else []
    if request.method == "POST" and template is not None:
        answers = {key: request.POST.get(key, "").strip()[:300] for key, _ in questions}
        empty = [label for key, label in questions if key.startswith("trou:") and not answers[key]]
        if empty:
            messages.error(request, "À compléter : " + ", ".join(empty) + ".")
        else:
            document = generation.generate(
                client, "lettre_mission", user=request.user, answers=answers
            )
            log_access(
                request, AccessLog.Action.CREATE, document, details={"généré": "lettre_mission"}
            )
            return redirect("clients:document_viewer_page", pk=client.pk, document_id=document.pk)
    values = request.POST
    return render_section(
        request,
        pk,
        "documents:lettre-de-mission",
        "documents/lettre/preparer.html",
        lambda c: {"template": template, "questions": questions, "values": values},
    )
