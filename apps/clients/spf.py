"""Récapitulatif des mandats SPF Finances d'un dossier (D-072).

Une ligne par mandat **utile à ce dossier** : TVA si le client dépose des déclarations TVA,
Biztax pour une société ou une association, Registre UBO si c'est le cabinet qui le dépose,
Tax-on-web pour une personne physique. Vert quand le mandat est signé, rouge sinon. Pas
d'alerte : c'est un simple récapitulatif, tenu à la main.
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
        kinds.append(Kind.BIZTAX)
        if client.ubo_filed_by == Client.UboFiler.CABINET:
            kinds.append(Kind.UBO)
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
