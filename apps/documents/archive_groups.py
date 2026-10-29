"""Archives rangées par année, puis par période (TVA) ou par thème (D-097).

Demande de Jeremy : « des espèces de dossiers 2025, 2026, 2027… et pour la TVA des sous-onglets
T1-26, T2-26, parce que deux documents à chaque fois ce n'est pas lisible ; pour les autres
documents, par thème (Biztax, avertissements-extraits de rôle…) ».

- Année : celle de la période TVA (déclaration, listing), sinon l'année citée dans le titre
  (« exercice 2025 »), sinon l'année d'ajout.
- TVA : un groupe par période (« T3-26 », « 09-26 ») qui réunit le XML, le PDF et le listing
  intracommunautaire de la même période ; les autres documents TVA par thème.
- Autres dossiers : un groupe par thème (le début du titre : « Biztax », « Avertissement-extrait
  de rôle ISOC »…).
Rien n'est déplacé ni renommé : ce n'est qu'une façon d'afficher la liste.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import Document

YEAR_IN_TITLE = re.compile(r"\b(20\d{2})\b")
FLAT_FOLDERS = {"courriels", "moniteur"}  # restent une simple liste


@dataclass
class Group:
    key: str
    label: str
    subtitle: str = ""
    documents: list[Document] = field(default_factory=list)


def _period_label(period_key: str) -> str:
    """« 2026-T3 » → « T3-26 » ; « 2026-09 » → « 09-26 »."""
    year, _, part = period_key.partition("-")
    return f"{part}-{year[2:]}"


def _theme(title: str) -> str:
    theme = title.split(" — ")[0]
    return re.sub(r"\s*\((PDF|XML|XBRL)[^)]*\)\s*$", "", theme).strip() or "Autres documents"


def group(client: Any, folder: str, documents: list[Document], year: str = "",
          period: str = "") -> dict[str, Any]:  # fmt: skip
    if folder in FLAT_FOLDERS or not documents:
        return {"grouped": False}
    from apps.vat.models import VatFiling

    periods: dict[Any, VatFiling] = {}
    for line in VatFiling.objects.filter(client=client):
        for doc_id in (line.xml_id, line.pdf_id, line.ic_xml_id, line.ic_pdf_id):
            if doc_id:
                periods[doc_id] = line
    by_year: dict[str, list[tuple[Document, VatFiling | None]]] = {}
    for document in documents:
        filing = periods.get(document.pk)
        if filing is not None:
            key = filing.period_key[:4]
        else:
            found = YEAR_IN_TITLE.findall(document.title)
            key = found[-1] if found else str(document.uploaded_at.year)
        by_year.setdefault(key, []).append((document, filing))
    years = sorted(by_year, reverse=True)
    selected = year if year in by_year else years[0]
    groups: dict[str, Group] = {}
    for document, filing in by_year[selected]:
        if filing is not None:
            key = f"p:{filing.period_key}"
            if key not in groups:
                groups[key] = Group(key, _period_label(filing.period_key),
                                    f"Période {filing.short_label}")  # fmt: skip
        else:
            theme = _theme(document.title)
            key = f"t:{theme}"
            groups.setdefault(key, Group(key, theme))
        groups[key].documents.append(document)
    period_groups = sorted((g for g in groups.values() if g.key.startswith("p:")),
                           key=lambda g: g.key, reverse=True)  # fmt: skip
    theme_groups = sorted((g for g in groups.values() if g.key.startswith("t:")),
                          key=lambda g: g.label)  # fmt: skip
    shown = period_groups + theme_groups
    if period and any(g.key == period for g in shown):
        shown = [g for g in shown if g.key == period]
    return {
        "grouped": True,
        "years": [(y, len(by_year[y])) for y in years],
        "year": selected,
        "period_tabs": [(g.key, g.label) for g in period_groups],
        "period": period,
        "groups": shown,
    }


# --- Classeur « Archives » : une seule page, années › sujets (D-105) ---------------------------

SUBJECTS: dict[str, tuple[str, str]] = {  # dossier → (libellé, couleur)
    "tva": ("TVA", "#4f46e5"),
    "isoc": ("ISOC", "#9333ea"),
    "ipp": ("IPP", "#be123c"),
    "comptes": ("Comptes annuels", "#b45309"),
    "legal": ("Légal et statuts", "#0f766e"),
    "moniteur": ("Moniteur belge", "#0e7490"),
    "administratif": ("Administratif", "#64748b"),
    "courriels": ("Courriels", "#0369a1"),
}


@dataclass
class Subject:
    folder: str
    label: str
    color: str
    documents: list[Document] = field(default_factory=list)
    # TVA : les périodes de l'année (« 01 »… ou « T1 »…), déposées ou non.
    periods: list[tuple[str, bool]] = field(default_factory=list)


@dataclass
class Year:
    year: str
    subjects: list[Subject]

    @property
    def count(self) -> int:
        return sum(len(s.documents) for s in self.subjects)


def _year_of(document: Document, filings: dict[Any, Any]) -> str:
    filing = filings.get(document.pk)
    if filing is not None:
        return str(filing.period_key[:4])
    found = YEAR_IN_TITLE.findall(document.title)
    return str(found[-1]) if found else str(document.uploaded_at.year)


def classeur(client: Any, documents: list[Document]) -> list[Year]:
    """Années (la plus récente d'abord), puis sujets dans l'ordre fixe de `SUBJECTS`.
    Seuls les sujets qui ont des documents apparaissent : rien de vide à parcourir."""
    from apps.vat.models import VatFiling

    filings: dict[Any, Any] = {}
    done: set[str] = set()
    for line in VatFiling.objects.filter(client=client):
        ids = [i for i in (line.xml_id, line.pdf_id, line.ic_xml_id, line.ic_pdf_id) if i]
        for doc_id in ids:
            filings[doc_id] = line
        if line.xml_id or line.pdf_id:
            done.add(line.period_key)
    years: dict[str, dict[str, Subject]] = {}
    for document in documents:
        if document.folder not in SUBJECTS:
            continue
        label, color = SUBJECTS[document.folder]
        by_folder = years.setdefault(_year_of(document, filings), {})
        by_folder.setdefault(document.folder, Subject(document.folder, label, color))
        by_folder[document.folder].documents.append(document)
    quarterly = getattr(client, "vat_periodicity", "") == "quarterly"
    result = []
    for year in sorted(years, reverse=True):
        subjects = [years[year][f] for f in SUBJECTS if f in years[year]]
        for subject in subjects:
            if subject.folder == "tva":
                keys = ([f"{year}-T{q}" for q in range(1, 5)] if quarterly
                        else [f"{year}-{m:02d}" for m in range(1, 13)])  # fmt: skip
                subject.periods = [(k.split("-", 1)[1], k in done) for k in keys]
        result.append(Year(year, subjects))
    return result
