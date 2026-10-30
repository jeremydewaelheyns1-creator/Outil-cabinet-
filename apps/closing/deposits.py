"""Cases de dépôt de l'exercice (D-113, D-115) : AG, BNB, ISOC, annexes 270, précompte
mobilier, fiches 281 (281.20 et 281.50 dans une seule case), listing clients.

Chaque dossier ne voit que ses cases (D-115) : listing clients seulement s'il est soumis à
TVA ; précompte mobilier seulement si l'AG a décidé un dividende ; le reste se retire dans la
case elle-même (« Retirer pour ce dossier »), gardé pour les années suivantes.

Une case = une échéance = des fichiers :
- cocher la case termine l'échéance correspondante (et la décocher la rouvre) ; terminer
  l'échéance ailleurs (échéancier) coche la case ;
- un fichier déposé dans la case est rangé aux archives du dossier et coche la case ;
- les comptes annuels XBRL et la déclaration Biztax XBRL déposés dans « Déposer des
  documents » cochent tout seuls la case BNB ou ISOC du bon exercice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone

from apps.clients.models import Client
from apps.core import events
from apps.core.models import Event, User
from apps.documents import services as documents
from apps.documents.models import Document
from apps.tasks.models import Task

from .models import ClosingYear, Deposit, DossierSetup

Kind = Deposit.Kind

# Échéance reliée (règles de config/taches/regles.yaml) et dossier d'archives des fichiers.
TASKS: dict[str, str] = {
    Kind.AG: "assemblee_generale",
    Kind.BNB: "comptes_annuels",
    Kind.ISOC: "isoc",
    Kind.LISTING: "listing_clients_tva",  # annuelle : l'année civile où l'exercice se termine
}
ANNUAL = {Kind.LISTING}
FOLDERS: dict[str, str] = {
    Kind.AG: "legal", Kind.BNB: "comptes", Kind.ISOC: "isoc",
    Kind.FICHES_281_50: "isoc", Kind.ANNEXES_270: "isoc", Kind.FICHES_281_20: "isoc",
    Kind.LISTING: "tva", Kind.PRECOMPTE: "isoc", Kind.UBO: "administratif",
}  # fmt: skip
# Ordre des cases sur la ligne ; 281.20 et 281.50 partagent la case « Fiches 281 ».
ORDER = [Kind.AG, Kind.BNB, Kind.ISOC, Kind.ANNEXES_270, Kind.PRECOMPTE,
         Kind.FICHES_281_20, Kind.FICHES_281_50, Kind.LISTING, Kind.UBO]  # fmt: skip
FICHES = (Kind.FICHES_281_20, Kind.FICHES_281_50)
# Nom court dans la case (toutes les cases tiennent sur une ligne) ; le nom complet est dans
# la fenêtre de la case.
BOX_LABEL: dict[str, str] = {Kind.PRECOMPTE: "Précompte", Kind.UBO: "UBO"}
VAT_SUBJECT = {"subject", "mixed", "franchise"}  # comme la règle listing_clients_tva
HINTS: dict[str, str] = {
    Kind.AG: "Assemblée générale ordinaire : procès-verbal",
    Kind.BNB: "Comptes annuels déposés à la Banque Nationale (XBRL, PDF)",
    Kind.ISOC: "Déclaration à l'impôt des sociétés (Biztax)",
    Kind.FICHES_281_50: "Fiches que le client établit pour les honoraires et commissions payés "
    "(Belcotax)",
    Kind.ANNEXES_270: "Annexes 270 jointes à la déclaration (270 MLH…)",
    Kind.FICHES_281_20: "Fiches des rémunérations de dirigeants (Belcotax)",
    Kind.LISTING: "Listing annuel des clients assujettis (Intervat), année civile",
    Kind.UBO: "Confirmation annuelle des bénéficiaires effectifs au registre UBO (MyMinfin)",
    Kind.PRECOMPTE: "Déclaration 273 S et paiement, dans les 15 jours après l'attribution "
    "du dividende",
}
SHORT: dict[str, str] = {
    Kind.AG: "AG", Kind.BNB: "BNB", Kind.ISOC: "ISOC", Kind.FICHES_281_50: "281.50",
    Kind.ANNEXES_270: "270", Kind.FICHES_281_20: "281.20", Kind.LISTING: "Listing",
    Kind.PRECOMPTE: "PM", Kind.UBO: "UBO",
}  # fmt: skip


def _period(year: ClosingYear, kind: str) -> str:
    return str(year.end.year) if kind in ANNUAL else f"EX-{year.end.isoformat()}"


def _task(year: ClosingYear, kind: str) -> Task | None:
    code = TASKS.get(kind)
    if code is None:
        return None
    return Task.objects.filter(
        client=year.client, kind=code, period_key=_period(year, kind)
    ).first()


@dataclass
class Box:
    """Une case de dépôt prête à afficher."""

    kind: str
    label: str
    short: str
    hint: str
    deposit: Deposit | None
    task: Task | None
    files: list[Document]
    name: str = ""  # nom court affiché dans la case
    deadline: date | None = None  # date limite sans échéance (précompte : AG + 15 jours)
    parts: list[Box] = field(default_factory=list)  # « Fiches 281 » : 281.20 et 281.50

    @property
    def items(self) -> list[Box]:
        return self.parts or [self]

    @property
    def done_on(self) -> date | None:
        if self.parts:
            dates = [p.done_on for p in self.parts]
            return max(d for d in dates if d) if all(dates) else None
        if self.deposit is not None and self.deposit.done_on:
            return self.deposit.done_on
        return None

    @property
    def done_count(self) -> int:
        return sum(1 for p in self.items if p.done_on)

    @property
    def due(self) -> date | None:
        dates = [p.task.due_date if p.task else p.deadline for p in self.items if not p.done_on]
        return min((d for d in dates if d), default=None)


def hidden_for(client: Client) -> list[str]:
    setup = DossierSetup.objects.filter(client=client).first()
    return list(setup.hidden_deposits) if setup else []


def kinds_for(client: Client) -> list[str]:
    """Les cases de dépôt du dossier (une société ; sans les cases retirées ; listing clients
    seulement si le dossier est soumis à TVA)."""
    if client.is_person:
        return []
    hidden = set(hidden_for(client))
    if client.vat_status not in VAT_SUBJECT:
        hidden.add(Kind.LISTING)
    return [k for k in ORDER if k not in hidden]


def boxes(year: ClosingYear, kinds: list[str]) -> list[Box]:
    if not year.dividend:
        kinds = [k for k in kinds if k != Kind.PRECOMPTE]  # pas de dividende : pas de case
    found = {d.kind: d for d in year.deposits.prefetch_related("documents")}
    periods = {f"EX-{year.end.isoformat()}", str(year.end.year)}
    tasks = {
        (t.kind, t.period_key): t
        for t in Task.objects.filter(
            client=year.client, kind__in=TASKS.values(), period_key__in=periods
        )
    }
    result: list[Box] = []
    fiches: list[Box] = []
    for kind in kinds:
        deposit = found.get(kind)
        task = tasks.get((TASKS.get(kind, ""), _period(year, kind)))
        files = list(deposit.documents.all()) if deposit else []
        box = Box(kind, Kind(kind).label, SHORT[kind], HINTS[kind], deposit, task, files)
        box.name = BOX_LABEL.get(kind, box.label)
        if kind == Kind.PRECOMPTE:
            ag = found.get(Kind.AG)
            box.deadline = ag.done_on + timedelta(days=15) if ag and ag.done_on else None
        if kind in FICHES:
            if not fiches:
                result.append(
                    Box("281", "Fiches 281", "281", "", None, None, [], "Fiches 281", parts=fiches)
                )
            fiches.append(box)
        else:
            result.append(box)
    for box in result:
        if box.parts:
            box.files = [f for p in box.parts for f in p.files]
    return result


def set_dividend(year: ClosingYear, value: bool | None, user: User | None) -> None:
    """« Dividende décidé à l'AG ? » (D-115) : oui → la case Précompte mobilier apparaît."""
    year.dividend = value
    year.save(update_fields=["dividend"])
    events.emit(
        "closing.dividend", subject=year.client, actor=user,
        payload={"exercice": year.label, "dividende": value},
    )  # fmt: skip


def complete(year_boxes: list[Box]) -> bool:
    return all(b.done_on for b in year_boxes)


def _sync_task(year: ClosingYear, kind: str, done: bool, user: User | None) -> None:
    task = _task(year, kind)
    if task is None:
        return
    if done and task.status != Task.Status.DONE:
        task.status, task.completed_at, task.completed_by = Task.Status.DONE, timezone.now(), user
        task.save(update_fields=["status", "completed_at", "completed_by", "updated_at"])
    elif not done and task.status == Task.Status.DONE:
        task.status, task.completed_at, task.completed_by = Task.Status.IN_PROGRESS, None, None
        task.save(update_fields=["status", "completed_at", "completed_by", "updated_at"])


def set_done(year: ClosingYear, kind: str, done: bool, user: User | None,
             on: date | None = None, sync: bool = True) -> Deposit:  # fmt: skip
    if kind not in Kind.values:
        raise ValueError("Case inconnue.")
    with transaction.atomic():
        deposit, _ = Deposit.objects.get_or_create(year=year, kind=kind)
        if done and deposit.done_on is None:
            deposit.done_on, deposit.done_by = on or timezone.localdate(), user
        elif not done:
            deposit.done_on, deposit.done_by = None, None
        deposit.save()
        if sync:
            _sync_task(year, kind, done, user)
    events.emit(
        "closing.deposit_done" if done else "closing.deposit_undone",
        subject=year.client, actor=user,
        payload={"exercice": year.label, "depot": kind},
    )  # fmt: skip
    return deposit


def add_file(year: ClosingYear, kind: str, upload: UploadedFile[bytes], user: User) -> Document:
    """Un fichier déposé dans la case : rangé aux archives du dossier, la case est cochée."""
    if kind not in Kind.values:
        raise ValueError("Case inconnue.")
    title = f"{Kind(kind).label} {year.label} — {upload.name or 'document'}"[:200]
    document = documents.store(year.client, upload, title=title, folder=FOLDERS[kind], user=user)
    attach(year, kind, document, user)
    return document


def attach(year: ClosingYear, kind: str, document: Document, user: User | None) -> None:
    deposit = set_done(year, kind, True, user)
    deposit.documents.add(document)


def hide(client: Client, kind: str, hidden: bool) -> None:
    if kind not in Kind.values:
        raise ValueError("Case inconnue.")
    setup, _ = DossierSetup.objects.get_or_create(client=client)
    current = [k for k in setup.hidden_deposits if k != kind]
    setup.hidden_deposits = current + ([kind] if hidden else [])
    setup.save()


def year_ending(client: Client, end: date | None) -> ClosingYear | None:
    if end is None:
        return None
    return ClosingYear.objects.filter(client=client, end=end).first()


def xbrl_received(client: Client, kind: str, end: date | None, assessment_year: int | None,
                  document: Document, user: User | None) -> None:  # fmt: skip
    """Comptes annuels ou Biztax XBRL rangés par « Déposer des documents » : la case du bon
    exercice se coche (si l'exercice a déjà sa ligne dans l'onglet Clôture)."""
    year = year_ending(client, end)
    if year is None and assessment_year:
        # Biztax : exercice d'imposition N = exercice comptable clôturé en N-1.
        year = ClosingYear.objects.filter(client=client, end__year=assessment_year - 1).first()
    if year is not None:
        attach(year, kind, document, user)


def document_found(
    client: Client, kind: str, end_year: int, document: Document, user: User | None
) -> ClosingYear | None:
    """Un document reconnu dans « Déposer des documents » (PV d'AG, comptes annuels, accusé
    Biztax ou Belcotax, annexe 270) : il rejoint la case de l'exercice qui se termine cette
    année-là, et la coche (D-114). Aucun exercice → rien n'est coché (le document reste rangé)."""
    if kind not in kinds_for(client):  # case retirée, ou pas de TVA → pas de listing
        return None
    year = ClosingYear.objects.filter(client=client, end__year=end_year).order_by("-end").first()
    if year is None:
        return None
    attach(year, kind, document, user)
    return year


@events.on("task.completed")
def task_completed_elsewhere(event: Event) -> None:
    """Échéance terminée dans l'échéancier : la case de dépôt correspondante se coche."""
    payload = event.payload or {}
    kind = next((k for k, code in TASKS.items() if code == payload.get("kind")), None)
    task = Task.objects.filter(pk=int(payload.get("task") or 0)).first()
    if kind is None or task is None:
        return
    if kind in ANNUAL and task.period_key.isdigit():
        # Listing clients 2025 : l'exercice qui se termine en 2025.
        years = ClosingYear.objects.filter(client=task.client, end__year=int(task.period_key))
        year = years.order_by("-end").first()
    elif task.period_key.startswith("EX-"):
        end = date.fromisoformat(task.period_key[3:])
        year = ClosingYear.objects.filter(client=task.client, end=end).first()
    else:
        return
    if year is not None and not year.deposits.filter(kind=kind, done_on__isnull=False).exists():
        set_done(year, kind, True, task.completed_by, sync=False)


@events.on("document.added")
def ubo_extract_added(event: Event) -> None:
    """Extrait du registre UBO rangé (page UBO ou « Déposer des documents ») : il rejoint la
    case « UBO » du dernier exercice terminé et la coche (D-117)."""
    pk = str((event.payload or {}).get("document") or "")
    document = Document.objects.filter(pk=pk, doc_type="extrait_ubo").first() if pk else None
    if document is None or Kind.UBO not in kinds_for(document.client):
        return
    day = timezone.localtime(document.uploaded_at).date()
    year = ClosingYear.objects.filter(client=document.client, end__lte=day).order_by("-end").first()
    if year is None or year.deposits.filter(kind=Kind.UBO, documents=document).exists():
        return
    attach(year, Kind.UBO, document, document.uploaded_by)
