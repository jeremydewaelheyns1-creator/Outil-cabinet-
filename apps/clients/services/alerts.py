"""Points d'attention d'un dossier : ce qui manque ou demande une action.

Affichés en tête de la synthèse du dossier, chacun avec un lien vers la rubrique à corriger.
Règles volontairement simples et lisibles ; d'autres s'ajouteront avec les modules (pièces
d'identité expirées, échéances proches, dossier anti-blanchiment à revoir…).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from apps.integrations.models import OfficialSnapshot, VatCheck

from ..models import Client, ContactPoint
from .ubo import UboAnalysis


@dataclass(frozen=True)
class Alert:
    level: str  # "danger", "warning" ou "info"
    message: str
    section: str  # rubrique du dossier (nom d'URL dans l'espace « clients »)


def dossier_alerts(client: Client, ubo: UboAnalysis | None) -> list[Alert]:
    from apps.tasks.models import Task  # import local : le module échéances dépend des clients

    alerts: list[Alert] = []
    entity = not client.is_person

    overdue = Task.objects.filter(client=client).overdue().count()
    if overdue:
        plural = "s" if overdue > 1 else ""
        alerts.append(Alert("danger", f"{overdue} échéance{plural} en retard", "tasks"))

    if client.bce_juridical_situation:
        alerts.append(
            Alert("danger", f"Situation à la BCE : {client.bce_juridical_situation}", "public_data")
        )
    if client.bce_status == "absent":
        alerts.append(
            Alert("warning", "Numéro absent de la BCE (entreprise arrêtée ?)", "public_data")
        )
    latest_check = client.vat_checks.first()
    if (
        latest_check is not None
        and latest_check.result == VatCheck.Result.INVALID
        and client.vat_status not in ("", Client.VatStatus.NOT_SUBJECT)
    ):
        alerts.append(
            Alert(
                "warning",
                "VIES : numéro de TVA non actif alors que le client est assujetti",
                "public_data",
            )
        )

    if entity and not client.enterprise_number:
        alerts.append(Alert("warning", "Numéro d'entreprise manquant", "identity"))
    if ubo is not None:
        if ubo.candidates and not ubo.declared:
            count = len(ubo.candidates)
            alerts.append(
                Alert(
                    "warning",
                    f"Bénéficiaires effectifs ({count}) : à comparer au registre UBO",
                    "ubo",
                )
            )
        elif ubo.candidates and not ubo.is_consistent:
            alerts.append(
                Alert("warning", "Bénéficiaires effectifs déclarés différents du calcul", "ubo")
            )
        if not ubo.candidates:
            alerts.append(
                Alert(
                    "info",
                    "Bénéficiaires effectifs : encodez actionnaires ou dirigeants",
                    "relations",
                )
            )
        elif not ubo.is_complete:
            alerts.append(Alert("info", "Actionnariat incomplet : calcul UBO partiel", "ubo"))

    if entity and client.enterprise_number:
        alerts.extend(_official_alerts(client))

    if client.is_person and not client.national_number:
        alerts.append(Alert("info", "Numéro national non renseigné", "identity"))
    if not client.contacts.filter(kind=ContactPoint.Kind.EMAIL).exists():
        alerts.append(Alert("info", "Aucune adresse e-mail", "identity"))
    if entity and not client.vat_status:
        alerts.append(Alert("info", "Statut TVA non renseigné", "identity"))
    if client.vat_status == Client.VatStatus.SUBJECT and not client.vat_periodicity:
        alerts.append(Alert("info", "Périodicité TVA non renseignée", "identity"))
    if entity and client.kind == Client.Kind.COMPANY and not client.fiscal_year_end_month:
        alerts.append(Alert("info", "Date de clôture de l'exercice non renseignée", "identity"))
    if not client.assignments.exists():
        alerts.append(Alert("info", "Aucun collaborateur affecté au dossier", "team"))
    return alerts


RECENT_PUBLICATION_DAYS = 45


def _official_alerts(client: Client) -> list[Alert]:
    """Ce que les sites officiels révèlent : publication récente, dirigeant non encodé."""
    from apps.integrations import official

    alerts: list[Alert] = []
    moniteur = official.latest(client, OfficialSnapshot.Source.MONITEUR, ok_only=True)
    if moniteur is not None:
        since = (date.today() - timedelta(days=RECENT_PUBLICATION_DAYS)).isoformat()
        recent = [p for p in moniteur.items if str(p.get("published_on", "")) >= since]
        if recent:
            first = recent[0]
            subject = ", ".join(first.get("tags") or []) or "publication"
            day = str(first.get("published_on", ""))
            alerts.append(
                Alert(
                    "warning",
                    f"Publication récente au Moniteur belge : {subject.lower()} "
                    f"({day[8:10]}/{day[5:7]}/{day[:4]})",
                    "moniteur",
                )
            )
    kbo = official.latest(client, OfficialSnapshot.Source.KBO, ok_only=True)
    missing = [c for c in official.compare_functions(client, kbo) if not c.matched]
    if missing:
        alerts.append(
            Alert(
                "warning",
                f"Dirigeants publiés à la BCE absents des relations ({len(missing)})",
                "public_data",
            )
        )
    return alerts
