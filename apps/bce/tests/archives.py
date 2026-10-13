"""Fabrique d'archives KBO Open Data fictives (mêmes fichiers et colonnes que les vraies)."""

import csv
import io
import zipfile
from pathlib import Path

HEADERS = {
    "meta": ["Variable", "Value"],
    "code": ["Category", "Code", "Language", "Description"],
    "enterprise": [
        "EnterpriseNumber", "Status", "JuridicalSituation", "TypeOfEnterprise",
        "JuridicalForm", "JuridicalFormCAC", "StartDate",
    ],
    "denomination": ["EntityNumber", "Language", "TypeOfDenomination", "Denomination"],
    "address": [
        "EntityNumber", "TypeOfAddress", "CountryNL", "CountryFR", "Zipcode", "MunicipalityNL",
        "MunicipalityFR", "StreetNL", "StreetFR", "HouseNumber", "Box", "ExtraAddressInfo",
        "DateStrikingOff",
    ],
    "activity": ["EntityNumber", "ActivityGroup", "NaceVersion", "NaceCode", "Classification"],
    "contact": ["EntityNumber", "EntityContact", "ContactType", "Value"],
    "establishment": ["EstablishmentNumber", "StartDate", "EnterpriseNumber"],
}  # fmt: skip

CODES = [
    ["JuridicalForm", "610", "FR", "Société à responsabilité limitée"],
    ["JuridicalForm", "610", "NL", "Besloten vennootschap"],
    ["JuridicalForm", "017", "FR", "Association sans but lucratif"],
    ["JuridicalSituation", "000", "FR", "Situation normale"],
    ["JuridicalSituation", "012", "FR", "Ouverture de faillite"],
    ["Nace2025", "56111", "FR", "Restauration à service complet"],
    ["Nace2008", "56101", "FR", "Restauration à service complet (2008)"],
    ["Status", "AC", "DE", "Aktiv"],
]


def dotted(number: str) -> str:
    return f"{number[:4]}.{number[4:7]}.{number[7:]}"


def _csv(header: list[str], rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def company_rows(number: str, name: str, *, city: str = "Namur", situation: str = "000",
                 form: str = "610") -> dict[str, list[list[str]]]:  # fmt: skip
    n = dotted(number)
    return {
        "enterprise": [[n, "AC", situation, "2", form, "", "15-03-2019"]],
        "denomination": [[n, "1", "001", name], [n, "2", "003", f"{name} Commercial"]],
        "address": [
            [n, "REGO", "", "", "5000", city, city, "Rue Fictive", "Rue Fictive", "12", "3", "", ""]
        ],
        "activity": [
            [n, "001", "2025", "56111", "MAIN"],
            [n, "001", "2008", "56101", "MAIN"],
            [n, "003", "2025", "47110", "SECO"],
        ],
        "contact": [[n, "ENT", "EMAIL", "info@fictif.test"], [n, "ENT", "TEL", "081 00 00 00"]],
    }


def build(path: Path, *, kind: str, number: int, tables: dict[str, list[list[str]]],
          deletes: dict[str, list[str]] | None = None, codes: bool = True) -> Path:  # fmt: skip
    meta = [
        ["SnapshotDate", "13-10-2026"],
        ["ExtractTimestamp", "13-10-2026 06:00:00"],
        ["ExtractType", kind],
        ["ExtractNumber", str(number)],
        ["Version", "1.0.0"],
    ]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("meta.csv", _csv(HEADERS["meta"], meta))
        if codes:
            archive.writestr("code.csv", _csv(HEADERS["code"], CODES))
        for name in ("enterprise", "denomination", "address", "activity", "contact"):
            rows = tables.get(name, [])
            if kind == "full":
                archive.writestr(f"{name}.csv", _csv(HEADERS[name], rows))
            else:
                key = "EnterpriseNumber" if name == "enterprise" else "EntityNumber"
                archive.writestr(
                    f"{name}_delete.csv",
                    _csv([key], [[dotted(n)] for n in (deletes or {}).get(name, [])]),
                )
                archive.writestr(f"{name}_insert.csv", _csv(HEADERS[name], rows))
    return path


def merge(*parts: dict[str, list[list[str]]]) -> dict[str, list[list[str]]]:
    merged: dict[str, list[list[str]]] = {}
    for part in parts:
        for table, rows in part.items():
            merged.setdefault(table, []).extend(rows)
    return merged
