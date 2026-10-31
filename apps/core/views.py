"""Accueil et journal des consultations (la sonde de santé est dans `health.py`)."""

from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.clients.models import Client

from .audit import log_access
from .capabilities import Capability
from .http import AppRequest
from .models import AccessLog, Event, Notification, User
from .permissions import require_capability


def _compliance(request: AppRequest) -> dict[str, int]:
    from apps.documents.compliance import summary_for

    return summary_for(request.user)


def home(request: AppRequest) -> HttpResponse:
    """Accueil personnel (D-063) : la période en cours pour MES dossiers."""
    from . import accueil

    today = timezone.localdate()
    context = accueil.build(request.user, today)
    shown = accueil.parse_month(request.GET.get("mois", ""))
    if shown is not None:  # sans JavaScript : les flèches rechargent l'Accueil
        context["calendar"] = accueil.calendar_for(request.user, today, shown)
    return render(request, "core/accueil.html", context)


def home_calendar(request: AppRequest) -> HttpResponse:
    """Calendrier fiscal de l'Accueil, mois par mois (flèches ‹ ›, D-104)."""
    from . import accueil

    today = timezone.localdate()
    shown = accueil.parse_month(request.GET.get("mois", "")) or today
    calendar = accueil.calendar_for(request.user, today, shown)
    return render(request, "core/_calendar.html", {"calendar": calendar})


def today_view(request: AppRequest) -> HttpResponse:
    """« Ma journée » (D-059) : ce qui est prêt à valider, à faire, et ce qui s'est fait seul."""
    from . import today

    clients = Client.objects.visible_to(request.user)
    context = {
        **today.build(request.user),
        "counts": {
            "active": clients.filter(status=Client.Status.ACTIVE).count(),
            "prospect": clients.filter(status=Client.Status.PROSPECT).count(),
            "companies": clients.filter(
                status=Client.Status.ACTIVE, kind=Client.Kind.COMPANY
            ).count(),
            "persons": clients.filter(status=Client.Status.ACTIVE, kind=Client.Kind.PERSON).count(),
        },
        "bce_alerts": clients.filter(status=Client.Status.ACTIVE)
        .exclude(bce_juridical_situation="")
        .order_by("name")[:10],
        "bce_missing": clients.filter(status=Client.Status.ACTIVE, bce_status="absent").order_by(
            "name"
        )[:10],
        "my_clients": clients.filter(assignments__user=request.user)
        .distinct()
        .order_by("name")[:10],
        "compliance": _compliance(request),
        "failed_events": Event.objects.filter(status=Event.Status.FAILED).count()
        if request.user.is_superuser
        else 0,
    }
    return render(request, "core/home.html", context)


@require_capability(Capability.AUDIT_VIEW)
def access_log(request: AppRequest) -> HttpResponse:
    entries = AccessLog.objects.select_related("user")
    action = request.GET.get("action", "")
    who = request.GET.get("qui", "").strip()
    what = request.GET.get("objet", "").strip()
    if action in AccessLog.Action.values:
        entries = entries.filter(action=action)
    if who:
        entries = entries.filter(user_email__icontains=who)
    if what:
        entries = entries.filter(object_repr__icontains=what)
    page = Paginator(entries, 100).get_page(request.GET.get("page"))
    return render(
        request,
        "core/access_log.html",
        {
            "page": page,
            "actions": AccessLog.Action.choices,
            "filters": {"action": action, "qui": who, "objet": what},
        },
    )


def settings_page(request: AppRequest) -> HttpResponse:
    """Outils d'administration, regroupés hors du menu quotidien."""
    tools = [
        (
            "Reprise FID-Manager",
            "Importer les clients depuis l'export Excel de FID-Manager (au démarrage).",
            "reprise:index",
            request.user.has_capability(Capability.REPRISE_IMPORT),
        ),
        (
            "Données BCE",
            "Suivi des mises à jour des données publiques des entreprises.",
            "bce:imports",
            request.user.has_capability(Capability.BCE_IMPORT),
        ),
        (
            "Journal des consultations",
            "Qui a ouvert, modifié ou exporté quoi (obligation anti-blanchiment et RGPD).",
            "core:access_log",
            request.user.has_capability(Capability.AUDIT_VIEW),
        ),
        (
            "Comptes et droits",
            "Créer les comptes des collègues, leurs profils et les portefeuilles.",
            "admin:index",
            request.user.is_staff,
        ),
        (
            "Délais du SPF",
            "Prolongations de délai annoncées par le SPF Finances : articles repérés, encodage.",
            "tasks:extensions",
            request.user.is_staff,
        ),
        (
            "Checklists de clôture",
            "Les checklists communes à tous les dossiers : sociétés (TVA ou non), indépendants "
            "(IPP), gestionnaire.",
            "closing:common",
            request.user.is_staff,
        ),
        (
            "Modèles de PV d'AG",
            "Les modèles Word du cabinet pour préparer les PV d'assemblée générale (D-120).",
            "lettre:models",
            request.user.is_staff,
        ),
        (
            "Réglages du cabinet",
            "Gestion hybride des dossiers (comptable « Hybride »).",
            "core:cabinet_settings",
            request.user.is_staff,
        ),
    ]
    allowed = [(title, text, url) for title, text, url, ok in tools if ok]
    extra = {"Modèles de PV d'AG": "?sorte=pv_ag"}
    # Tout le monde a au moins l'affichage (mode sombre, D-119).
    themes = User.Theme.choices
    links = [(title, text, url, extra.get(title, "")) for title, text, url in allowed]
    return render(request, "core/settings.html", {"tools": links, "themes": themes})


@require_POST
def set_theme(request: AppRequest) -> HttpResponse:
    """Affichage clair, sombre ou comme l'ordinateur (D-119) : propre à chaque personne."""
    value = request.POST.get("theme", "")
    if value in User.Theme.values:
        request.user.theme = value
        request.user.save(update_fields=["theme"])
    return redirect("core:settings")


def notifications(request: AppRequest) -> HttpResponse:
    """Les notifications de l'employé ; les ouvrir les marque comme lues."""
    items = list(Notification.objects.filter(user=request.user)[:50])
    unread = [n.pk for n in items if n.read_at is None]
    response = render(request, "core/notifications.html", {"items": items, "unread": unread})
    Notification.objects.filter(pk__in=unread).update(read_at=timezone.now())
    return response


def my_agenda(request: AppRequest) -> HttpResponse:
    """« Ma journée » › Mon agenda : la journée heure par heure, on y ajoute son temps."""
    from datetime import date as _date

    from apps.timesheet import services as timesheet
    from apps.timesheet.forms import TimeEntryForm
    from apps.timesheet.models import TimeEntry

    today = timezone.localdate()
    try:
        day = _date.fromisoformat(request.GET.get("jour", ""))
    except ValueError:
        day = today
    editing = None
    if request.GET.get("modifier", "").isdigit():
        editing = TimeEntry.objects.filter(
            user=request.user, pk=int(request.GET["modifier"])
        ).first()
    initial: dict[str, object] = {"day": day}
    if request.GET.get("dossier", "").isdigit():
        initial["client"] = int(request.GET["dossier"])
    if request.GET.get("texte"):
        initial["description"] = request.GET["texte"][:200]
    form = TimeEntryForm(instance=editing, initial=initial, user=request.user)
    visible = Client.objects.visible_to(request.user).exclude(status=Client.Status.FORMER)
    context = {
        **timesheet.day_view(request.user, day, today),
        **timesheet.deadlines_of(request.user, day),
        "form": form,
        "editing": editing,
        "today": today,
        "mode": "echeance" if request.GET.get("ajouter") == "echeance" else "temps",
        "deadline_clients": visible.order_by("name", "first_name"),
        "reminders": timesheet.reminders_today(request.user, today),
    }
    return render(request, "core/agenda.html", context)


@require_POST
def agenda_deadline(request: AppRequest) -> HttpResponse:
    """« Créer une échéance » depuis l'agenda (D-061)."""
    from datetime import date as _date
    from datetime import time as _time

    from django.contrib import messages
    from django.core.exceptions import ValidationError

    from apps.tasks import deadlines

    back = f"{reverse('core:agenda')}?jour={request.POST.get('jour', '')}"
    client = (
        Client.objects.visible_to(request.user).filter(pk=request.POST.get("dossier") or 0).first()
    )
    try:
        if client is None:
            raise ValidationError("Choisissez le dossier.")
        day = _date.fromisoformat(request.POST.get("jour", ""))
        at = _time.fromisoformat(request.POST["heure"]) if request.POST.get("heure") else None
        until = _time.fromisoformat(request.POST["fin"]) if request.POST.get("fin") else None
        deadlines.add(request.user, client=client, day=day, at=at, until=until,
                      comment=request.POST.get("commentaire", ""),
                      remind=request.POST.get("rappel") == "1")  # fmt: skip
    except (ValidationError, ValueError) as error:
        text = " ".join(error.messages) if isinstance(error, ValidationError) else "Date invalide."
        messages.error(request, f"Échéance non créée : {text}")
        return redirect(f"{back}&ajouter=echeance")
    messages.success(request, "Échéance ajoutée.")
    return redirect(back)


def cabinet_settings(request: AppRequest) -> HttpResponse:
    """Réglages du cabinet (administrateurs) : la gestion hybride des dossiers (D-063)."""
    from django import forms

    from .models import CabinetSettings

    if not request.user.is_staff:
        raise PermissionDenied

    class SettingsForm(forms.ModelForm[CabinetSettings]):
        class Meta:
            model = CabinetSettings
            fields = ("hybrid_management", "hybrid_release_days")

    class MandatesForm(forms.ModelForm[CabinetSettings]):
        class Meta:
            model = CabinetSettings
            fields = ("name", "enterprise_number", "spf_mandates_url")

    class AiForm(forms.ModelForm[CabinetSettings]):
        class Meta:
            model = CabinetSettings
            fields = ("ai_personal_data",)

    settings = CabinetSettings.current()
    if request.method == "POST" and request.POST.get("action") == "ia":
        ai_form = AiForm(request.POST, instance=settings)
        if ai_form.is_valid():
            ai_form.save()
            details = {"écran": "réglages du cabinet", "partie": "assistant IA",
                       "documents des clients": settings.ai_personal_data}  # fmt: skip
            log_access(request, AccessLog.Action.UPDATE, settings, details=details)
            messages.success(request, "Réglage de l'assistant IA enregistré.")
        return redirect("core:cabinet_settings")
    if request.method == "POST" and request.POST.get("action") in {"logo", "retirer_logo"}:
        return _logo_change(request, settings)
    if request.method == "POST" and request.POST.get("action") == "mandats":
        mandates_form = MandatesForm(request.POST, instance=settings)
        if mandates_form.is_valid():
            mandates_form.save()
            from .cabinet import forget

            forget()  # le nouveau nom s'affiche tout de suite
            details = {"écran": "réglages du cabinet", "partie": "identité du cabinet"}
            log_access(request, AccessLog.Action.UPDATE, settings, details=details)
            messages.success(request, "Identité du cabinet enregistrée.")
            return redirect("core:cabinet_settings")
        form = SettingsForm(instance=settings)
        context = {"form": form, "mandates_form": mandates_form, "settings": settings,
                   "ai_form": AiForm(instance=settings), "ai_on": _ai_on()}  # fmt: skip
        return render(request, "core/cabinet_settings.html", context)
    form = SettingsForm(request.POST or None, instance=settings)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_access(
            request, AccessLog.Action.UPDATE, settings, details={"écran": "réglages du cabinet"}
        )
        messages.success(request, "Réglages enregistrés.")
        return redirect("core:cabinet_settings")
    context = {"form": form, "mandates_form": MandatesForm(instance=settings), "settings": settings,
               "ai_form": AiForm(instance=settings), "ai_on": _ai_on()}  # fmt: skip
    return render(request, "core/cabinet_settings.html", context)


def _ai_on() -> bool:
    from apps.ai import client as ai

    return ai.enabled()


def _logo_change(request: AppRequest, settings: Any) -> HttpResponse:
    """Logo des signatures : déposé (refait en PNG propre) ou retiré, par un administrateur."""
    from django.core.exceptions import ValidationError

    from . import logo

    if request.POST["action"] == "retirer_logo":
        settings.signature_logo = b""
        settings.save(update_fields=["signature_logo"])
        messages.success(request, "Logo retiré des signatures.")
    else:
        upload = request.FILES.get("logo")
        try:
            if upload is None:
                raise ValidationError("Choisissez une image.")
            settings.signature_logo = logo.prepare(upload.read())
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("core:cabinet_settings")
        settings.save(update_fields=["signature_logo"])
        messages.success(request, "Logo enregistré : il apparaît dans les signatures d'e-mails.")
    details = {"écran": "réglages du cabinet", "logo": request.POST["action"]}
    log_access(request, AccessLog.Action.UPDATE, settings, details=details)
    return redirect("core:cabinet_settings")


def signature_logo(request: AppRequest) -> HttpResponse:
    """Le logo des signatures, pour l'aperçu dans l'outil (employés connectés)."""
    from .models import CabinetSettings

    data = bytes(CabinetSettings.current().signature_logo or b"")
    if not data:
        raise Http404
    response = HttpResponse(data, content_type="image/png")
    response["Cache-Control"] = "private, max-age=300"
    return response
