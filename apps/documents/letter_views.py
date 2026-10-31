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


def _kind(request: AppRequest) -> str:
    value = request.GET.get("sorte") or request.POST.get("sorte") or LetterTemplate.Kind.LETTER
    return value if value in LetterTemplate.Kind.values else LetterTemplate.Kind.LETTER


def _list_url(kind: str) -> str:
    from django.urls import reverse

    url = reverse("lettre:models")
    return f"{url}?sorte={kind}" if kind != LetterTemplate.Kind.LETTER else url


def models_page(request: AppRequest) -> HttpResponse:
    """Liste des modèles déposés et dépôt d'un nouveau (lettre de mission ou PV d'AG)."""
    _admin(request)
    kind = _kind(request)
    if request.method == "POST" and request.POST.get("exemple") == "1":
        return _from_example(request, kind)
    if request.method == "POST":
        upload = request.FILES.get("modele")
        if upload is None:
            messages.error(request, "Choisissez le fichier Word du modèle.")
            return redirect(_list_url(kind))
        content = upload.read()
        try:
            letter.check_upload(upload.name or "", content)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect(_list_url(kind))
        found = letter.holes(content, kind)
        template = LetterTemplate.objects.create(
            kind=kind,
            name=(upload.name or "modele.docx")[:200],
            content=content,
            holes={
                h.key: {"field": h.guess, "label": letter.proposed_label(h, kind)}
                for h in found
                if h.guess
            },
            uploaded_by=request.user,
        )
        log_access(request, AccessLog.Action.IMPORT, template, details={"modèle": kind})
        messages.success(
            request,
            f"Modèle déposé : {len(found)} trou(s) repéré(s). Vérifiez ce que l'outil propose.",
        )
        return redirect("lettre:model", template.pk)
    templates = LetterTemplate.objects.filter(kind=kind).select_related("uploaded_by")
    context = {"templates": templates, "kind": kind, "is_ag": kind == LetterTemplate.Kind.AG,
               "assistant_reads": _assistant_reads()}  # fmt: skip
    return render(request, "documents/lettre/modeles.html", context)


def _from_example(request: AppRequest, kind: str) -> HttpResponse:
    """Un document déjà rempli pour un client devient un modèle (D-124). Le document d'origine
    n'est pas gardé ; le modèle obtenu est à relire avant d'être activé."""
    from apps.clients.views import _visible_clients

    from . import from_example

    upload = request.FILES.get("modele")
    client = _visible_clients(request).filter(pk=request.POST.get("client") or 0).first()
    if upload is None or client is None:
        messages.error(
            request, "Choisissez le document Word rempli et le client pour qui il a été fait."
        )
        return redirect(_list_url(kind))
    content = upload.read()
    try:
        letter.check_upload(upload.name or "", content)
        result = from_example.convert(content, client)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
        return redirect(_list_url(kind))
    del content  # le document rempli n'est gardé nulle part
    assisted = 0
    from apps.ai import client as ai

    if ai.enabled() and ai.personal_data_allowed():
        from apps.ai import templates_assist

        try:
            extra = templates_assist.residuals(
                from_example.text_of(result.content), list(from_example.MARKERS), request.user
            )
        except ai.Unavailable:
            extra = []
        if extra:
            again = from_example.convert(result.content, client, extra)
            assisted = sum(again.counts.values())
            result = from_example.Conversion(again.content, result.counts)
    template = LetterTemplate.objects.create(
        kind=kind,
        name=f"Modèle tiré de « {(upload.name or 'document.docx')[:150]} »",
        content=result.content,
        holes=from_example.holes_for(result.content, kind),
        origin={"exemple": True, "remplace": result.report(), "assistant": assisted},
        uploaded_by=request.user,
    )
    details = {"modèle": kind, "depuis": "document rempli", "client": client.pk}
    log_access(request, AccessLog.Action.IMPORT, template, details=details)
    messages.success(
        request,
        "Modèle créé à partir du document rempli. Relisez-le : tout ce qui resterait du client "
        "d'origine serait recopié chez les autres.",
    )
    return redirect("lettre:model", template.pk)


def model_download(request: AppRequest, template_id: int) -> HttpResponse:
    """Le modèle Word tel que l'outil l'a préparé (pour le relire ou le retoucher dans Word)."""
    _admin(request)
    template = get_object_or_404(LetterTemplate, pk=template_id)
    response = HttpResponse(
        bytes(template.content),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    response["Content-Disposition"] = f'attachment; filename="modele-{template.pk}.docx"'
    log_access(request, AccessLog.Action.EXPORT, template, details={"modèle": "téléchargé"})
    return response


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
            return redirect(_list_url(template.kind))
        if action == "assistant":
            from apps.ai import client as ai
            from apps.ai import templates_assist

            try:
                found_holes, found_options = templates_assist.suggest(template, request.user)
            except ai.Unavailable as error:
                messages.error(request, str(error))
            else:
                if template.active:
                    template.active = False  # à revoir avant de resservir
                    template.save(update_fields=["active"])
                messages.success(
                    request,
                    f"L'assistant propose {found_holes} trou(s) et {found_options} passage(s) à "
                    "options : "
                    "vérifiez, puis enregistrez et activez.",
                )
            log_access(request, AccessLog.Action.UPDATE, template, details={"modèle": "assistant"})
            return redirect("lettre:model", template.pk)
        _save(request, template, content)
        if action == "activer":
            missing = letter.problems(template)
            if missing:
                messages.error(request, "Pas encore utilisable : " + " ; ".join(missing) + ".")
            else:
                with transaction.atomic():
                    if template.kind == LetterTemplate.Kind.LETTER:  # PV d'AG : plusieurs
                        others = LetterTemplate.objects.filter(kind=template.kind)
                        others.exclude(pk=template.pk).update(active=False)
                    template.active = True
                    template.save(update_fields=["active"])
                messages.success(request, "Modèle activé : il sert pour les nouveaux documents.")
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
            "proposed": (template.holes.get(h.key) or {}).get("source") == "assistant",
        }
        for h in letter.holes(content, template.kind)
    ]
    is_ag = template.kind == LetterTemplate.Kind.AG
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
        "checks": [] if is_ag else letter.checks(content, template.holes),
        "problems": letter.problems(template),
        "choices": letter.choices(template.kind),
        "conditions": list(letter.conditions(template.kind).items()),
        "ask": letter.ASK,
        "is_ag": is_ag,
        "forms": letter.FORMS,
        "list_url": _list_url(template.kind),
        "assistant": _assistant_on(),
    }
    return render(request, "documents/lettre/modele.html", context)


def _assistant_reads() -> bool:
    from apps.ai import client as ai

    return ai.enabled() and ai.personal_data_allowed()


def _assistant_on() -> bool:
    from apps.ai import client as ai

    return ai.enabled()


def _save(request: AppRequest, template: LetterTemplate, content: bytes) -> None:
    allowed = {code for code, _ in letter.choices(template.kind)}
    conditions = letter.conditions(template.kind)
    holes = {}
    for hole in letter.holes(content, template.kind):
        field = request.POST.get(f"trou-{hole.key}", "")
        if field in allowed:
            label = request.POST.get(f"libelle-{hole.key}", "").strip()[:120]
            holes[hole.key] = {"field": field, "label": label}
    options = {}
    for index, _ in letter.paragraphs(content):
        condition = request.POST.get(f"option-{index}", "")
        if condition and condition in conditions:
            label = request.POST.get(f"question-{index}", "").strip()[:160]
            options[str(index)] = {"condition": condition, "end": index, "label": label}
    found = {c.code for c in letter.checks(content, holes) if c.excerpt}
    template.holes = holes
    template.options = options
    template.checks = [code for code in request.POST.getlist("verifie") if code in found]
    if template.kind == LetterTemplate.Kind.AG:
        template.forms = [f for f in request.POST.getlist("forme") if f in letter.FORMS]
    template.save(update_fields=["holes", "options", "checks", "forms"])
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
