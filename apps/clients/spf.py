"""Récapitulatif des mandats SPF Finances d'un dossier (D-072 à D-074).

Une ligne par mandat **utile à ce dossier** : TVA si le client dépose des déclarations TVA ;
Biztax, Registre UBO et Finprof pour une société ou une association (le cabinet dépose le
registre UBO) ; Tax-on-web pour une personne physique ; Contentieux pour tous. Vert quand le
mandat est signé, rouge sinon. Pas d'alerte : un simple récapitulatif, tenu à la main.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import Client, SpfMandate

Kind = SpfMandate.Kind
Status = SpfMandate.Status


def needed(client: Client) -> list[str]:
    kinds: list[str] = []
    if client.vat_status in (Client.VatStatus.SUBJECT, Client.VatStatus.MIXED):
        kinds.append(Kind.VAT)
    if client.is_person:
        kinds.append(Kind.IPP)
    else:
        kinds += [Kind.BIZTAX, Kind.UBO, Kind.FINPROF]
    kinds.append(Kind.DISPUTE)
    return kinds


@dataclass
class Line:
    kind: str
    label: str
    status: str
    status_label: str
    mandate: SpfMandate | None

    @property
    def short(self) -> str:
        """Libellé court pour l'encadré (« Finprof » au lieu de « Finprof (situation fiscale) »)."""
        return self.label.split(" (")[0]

    @property
    def level(self) -> str:
        levels: dict[str, str] = {Status.SIGNED: "ok", Status.REQUESTED: "warning"}
        return levels.get(self.status, "danger")


def lines(client: Client) -> list[Line]:
    existing = {m.kind: m for m in client.spf_mandates.all()}
    result = []
    for kind in needed(client):
        mandate = existing.get(kind)
        status = mandate.status if mandate else Status.MISSING
        result.append(Line(kind, Kind(kind).label, status, Status(status).label, mandate))
    return result


# --- « Demander les mandats manquants » (D-075) -----------------------------------------------

# Ce que le client lit dans l'e-mail pour chaque mandat.
CLIENT_LABELS: dict[str, str] = {
    Kind.VAT: "TVA (déclarations TVA dans Intervat)",
    Kind.BIZTAX: "Biztax (déclaration à l'impôt des sociétés)",
    Kind.UBO: "Registre UBO (bénéficiaires effectifs)",
    Kind.IPP: "Tax-on-web (déclaration à l'impôt des personnes physiques)",
    Kind.FINPROF: "Finprof (consultation de votre situation fiscale)",
    Kind.DISPUTE: "Contentieux (réclamations auprès de l'administration)",
}


def missing(client: Client) -> list[Line]:
    """Les lignes rouges : mandats ni signés ni demandés."""
    return [line for line in lines(client) if line.status == Status.MISSING]


def unsigned(client: Client) -> list[Line]:
    """Rouges et oranges : tout ce que le client doit encore signer (demande ou rappel)."""
    return [line for line in lines(client) if line.status != Status.SIGNED]


def email(client: Client, kinds: list[str], url: str, reminder: bool = False) -> tuple[str, str]:
    """Objet et texte de l'e-mail au client : tous ses mandats à signer, en une fois.

    Aucune donnée sensible : le nom des mandats, le lien public du SPF, la marche à suivre."""
    from django.conf import settings

    count = len(kinds)
    plural = "s" if count > 1 else ""
    subject = (
        f"{'Rappel : ' if reminder else ''}{count} mandat{plural} à signer pour le SPF Finances"
    )
    greeting = client.greeting
    items = "\n".join(f"- {CLIENT_LABELS[k]}" for k in kinds)
    who = "au nom de l'entreprise" if not client.is_person else "en votre nom"
    body = (
        f"{greeting}\n\n"
        f"Pour que nous puissions gérer vos obligations auprès du SPF Finances, nous avons créé "
        f"{'ces' if count > 1 else 'ce'} mandat{plural} à votre nom. Il vous reste à "
        f"{'les' if count > 1 else 'le'} signer :\n\n{items}\n\n"
        f"1. Ouvrez l'application des mandats du SPF : {url}\n"
        f"2. Connectez-vous avec itsme ou votre carte d'identité, {who}.\n"
        f"3. Signez les mandats créés par {settings.CABINET_NAME}.\n\n"
        "Cela prend deux minutes. N'hésitez pas à nous appeler en cas de question.\n"
    )
    return subject, body


def mark_requested(client: Client, kinds: list[str], user: Any) -> None:
    from django.utils import timezone

    for kind in kinds:
        SpfMandate.objects.update_or_create(
            client=client,
            kind=kind,
            defaults={"status": Status.REQUESTED, "updated_at": timezone.now(),
                      "updated_by": user},
        )  # fmt: skip
