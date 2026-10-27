"""Récapitulatif des mandats SPF Finances d'un dossier (D-072 à D-074).

Une ligne par mandat **utile à ce dossier** : TVA si le client dépose des déclarations TVA ;
Biztax, Registre UBO et Finprof pour une société ou une association (le cabinet dépose le
registre UBO) ; Tax-on-web pour une personne physique ; Contentieux pour tous. Vert quand le
mandat est signé, rouge sinon. Pas d'alerte : un simple récapitulatif, tenu à la main.
"""

from __future__ import annotations

from dataclasses import dataclass

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
