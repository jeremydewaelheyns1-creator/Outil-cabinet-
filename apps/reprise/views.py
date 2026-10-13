"""Écrans de reprise : déposer un export, lire l'analyse, confirmer l'import."""

from django import forms
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.audit import log_access
from apps.core.capabilities import Capability
from apps.core.http import AppRequest
from apps.core.models import AccessLog
from apps.core.permissions import require_capability

from .importer import ImportFileError, run_import
from .models import ImportBatch

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class UploadForm(forms.Form):
    file = forms.FileField(label="Export clients (Excel .xlsx)")

    def clean_file(self) -> object:
        upload = self.cleaned_data["file"]
        if not upload.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("Seuls les fichiers Excel .xlsx sont acceptés.")
        if upload.size > MAX_UPLOAD_BYTES:
            raise forms.ValidationError("Fichier trop volumineux (20 Mo maximum).")
        return upload


@require_capability(Capability.REPRISE_IMPORT)
def index(request: AppRequest) -> HttpResponse:
    form = UploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["file"]
        batch = ImportBatch(file_name=upload.name[:255], uploaded_by=request.user)
        try:
            report = run_import(upload, file_name=upload.name, apply=False, actor=request.user)
        except ImportFileError as exc:
            form.add_error("file", str(exc))
        else:
            upload.seek(0)
            batch.stored_file.save(upload.name, upload, save=False)
            batch.analysis = report.as_json()
            batch.save()
            return redirect("reprise:detail", pk=batch.pk)
    return render(
        request,
        "reprise/index.html",
        {"form": form, "batches": ImportBatch.objects.select_related("uploaded_by")[:30]},
    )


@require_capability(Capability.REPRISE_IMPORT)
def detail(request: AppRequest, pk: int) -> HttpResponse:
    batch = get_object_or_404(ImportBatch, pk=pk)
    report = batch.result or batch.analysis
    return render(request, "reprise/detail.html", {"batch": batch, "report": report})


@require_POST
@require_capability(Capability.REPRISE_IMPORT)
def apply(request: AppRequest, pk: int) -> HttpResponse:
    batch = get_object_or_404(ImportBatch, pk=pk, status=ImportBatch.Status.ANALYSED)
    if not batch.stored_file:
        messages.error(request, "Le fichier n'est plus disponible : déposez-le à nouveau.")
        return redirect("reprise:detail", pk=batch.pk)
    with batch.stored_file.open("rb") as handle:
        report = run_import(handle, file_name=batch.file_name, apply=True, actor=request.user)
    batch.result = report.as_json()
    batch.status = ImportBatch.Status.APPLIED
    batch.applied_at = timezone.now()
    batch.discard_file()
    batch.save()
    log_access(
        request,
        AccessLog.Action.IMPORT,
        batch,
        details={"créés": report.created, "complétés": report.updated, "ignorés": report.skipped},
    )
    messages.success(
        request,
        f"Import terminé : {report.created} fiche(s) créée(s), {report.updated} complétée(s).",
    )
    return redirect("reprise:detail", pk=batch.pk)


@require_POST
@require_capability(Capability.REPRISE_IMPORT)
def discard(request: AppRequest, pk: int) -> HttpResponse:
    batch = get_object_or_404(ImportBatch, pk=pk, status=ImportBatch.Status.ANALYSED)
    batch.discard_file()
    batch.status = ImportBatch.Status.DISCARDED
    batch.save()
    messages.info(request, "Import abandonné, fichier supprimé.")
    return redirect("reprise:index")
