"""Documents du SPF Finances déposés dans « Déposer des documents » : reconnus et classés (D-084).

Complète le dépôt unique (D-041), qui reconnaît déjà les déclarations TVA d'Intervat (XML et
PDF) et les cartes d'identité. Ici : les autres courriers et documents du SPF —
avertissements-extraits de rôle (IPP, ISOC, IPM), accusés de réception Biztax et Tax-on-web,
listing clients annuel, avis de rectification, demandes de renseignements, versements
anticipés, compte courant TVA.

Comment :
1. le texte du PDF (pdftotext ; pour un courrier scanné sans texte, lecture de la 1re page sur
   le serveur) ;
2. le **type** par des mots sûrs (« avertissement-extrait de rôle » + « impôt des sociétés »…) ;
   aucun type sûr → rien n'est deviné ;
3. le **dossier** par le numéro d'entreprise ou le numéro national imprimé (contrôles
   modulo 97), parmi les dossiers visibles de la personne qui dépose ; le numéro du cabinet
   est ignoré ; le numéro national ne sert qu'à la recherche (jamais gardé, affiché ni
   journalisé) ;
4. un seul dossier et un type sûr → rangé dans les archives (ISOC, IPP, TVA ou Administratif)
   avec un titre clair ; un courrier qui demande une action (demande de renseignements, avis
   de rectification) est rangé « à revoir ». Sinon → « À classer », avec la raison.
Aucune IA : des règles lisibles, faciles à compléter.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from django.db.models import QuerySet
from stdnum.be import nn as be_nn

from apps.clients.models import Client
from apps.core.text import normalize_text
from apps.vat import intervat


@dataclass(frozen=True)
class Kind:
    slug: str
    label: str
    words: tuple[tuple[str, ...], ...]  # tous les groupes doivent avoir au moins un mot présent
    folder_person: str  # dossier d'archives pour une personne physique
    folder_entity: str  # … pour une société ou une association
    action: bool = False  # courrier qui demande une réponse : rangé « à revoir »


AER = ("avertissement-extrait de role", "avertissement extrait de role", "aanslagbiljet")
KINDS: tuple[Kind, ...] = (
    Kind("aer_isoc", "Avertissement-extrait de rôle ISOC",
         (AER, ("des societes", "vennootschapsbelasting")), "isoc", "isoc"),
    Kind("aer_ipm", "Avertissement-extrait de rôle IPM",
         (AER, ("personnes morales", "rechtspersonenbelasting")), "isoc", "isoc"),
    Kind("aer_ipp", "Avertissement-extrait de rôle IPP",
         (AER, ("personnes physiques", "personenbelasting")), "ipp", "ipp"),
    Kind("biztax", "Biztax — accusé de réception de la déclaration",
         (("biztax",), ("accuse de reception", "ontvangstbewijs", "bien ete deposee",
                        "bien ete enregistree", "a ete deposee")), "isoc", "isoc"),
    Kind("tax_on_web", "Tax-on-web — accusé de réception de la déclaration IPP",
         (("tax-on-web", "taxonweb", "myminfin"), ("accuse de reception", "ontvangstbewijs"),
          ("impot des personnes physiques", "personenbelasting", "declaration ipp")),
         "ipp", "ipp"),
    Kind("listing_clients", "Listing clients annuel (TVA)",
         (("listing annuel", "listing des clients", "klantenlisting", "jaarlijkse lijst"),
          ("assujetti", "btw-plichtige", "tva", "btw")), "tva", "tva"),
    Kind("compte_tva", "Compte courant TVA",
         (("compte courant tva", "compte-courant tva", "btw-rekening-courant"),), "tva", "tva"),
    Kind("rectification", "Avis de rectification de la déclaration",
         (("avis de rectification", "bericht van wijziging"),), "ipp", "isoc", action=True),
    Kind("renseignements", "Demande de renseignements",
         (("demande de renseignements", "vraag om inlichtingen"),), "ipp", "isoc", action=True),
    Kind("versements_anticipes", "Versements anticipés",
         (("versements anticipes", "versement anticipe", "voorafbetaling"),
          ("avis", "rappel", "aperçu", "apercu", "decompte", "overzicht")), "ipp", "isoc"),
)  # fmt: skip
YEAR = re.compile(r"exercice\s+d.imposition\s*:?\s*(20\d{2})|aanslagjaar\s*:?\s*(20\d{2})", re.I)
NATIONAL = re.compile(r"(?<!\d)(\d{2})[.\s]?(\d{2})[.\s]?(\d{2})[-.\s]?(\d{3})[.\s]?(\d{2})(?!\d)")


@dataclass
class Found:
    kind: Kind
    year: int | None
    clients: list[Client]  # dossiers retrouvés (0, 1 ou plusieurs)


def _scan_text(content: bytes) -> str:
    """Courrier scanné (PDF sans texte) : 1re page lue sur le serveur, fichiers effacés."""
    pdftoppm, tesseract = shutil.which("pdftoppm"), shutil.which("tesseract")
    if not pdftoppm or not tesseract:
        return ""
    langs = subprocess.run(  # noqa: S603 (commande fixe)
        [tesseract, "--list-langs"], capture_output=True, text=True, timeout=10, check=False
    ).stdout.split()
    lang = "fra+eng" if "fra" in langs else "eng"
    with tempfile.TemporaryDirectory(prefix="spf-") as folder:
        source = Path(folder) / "source.pdf"
        source.write_bytes(content)
        subprocess.run(  # noqa: S603 (commande fixe, chemins du dossier temporaire)
            [pdftoppm, "-r", "250", "-png", "-f", "1", "-l", "1", str(source), f"{folder}/p"],
            capture_output=True, timeout=60, check=False,
        )  # fmt: skip
        pages = sorted(Path(folder).glob("p*.png"))
        if not pages:
            return ""
        result = subprocess.run(  # noqa: S603 (commande fixe)
            [tesseract, str(pages[0]), "-", "-l", lang], capture_output=True, text=True,
            timeout=60, check=False,
        )  # fmt: skip
        return result.stdout


def text_of(content: bytes) -> str:
    text = intervat.pdf_text(content)
    if len(text.strip()) < 40:
        text = _scan_text(content)
    return text


def kind_of(text: str) -> Kind | None:
    plain = normalize_text(text)
    for kind in KINDS:
        if all(any(word in plain for word in group) for group in kind.words):
            return kind
    return None


def _national_numbers(text: str) -> set[str]:
    found = set()
    for match in NATIONAL.finditer(text):
        digits = "".join(match.groups())
        if be_nn.is_valid(digits):
            found.add(digits)
    return found


def identify(text: str, clients: QuerySet[Client], cabinet_number: str = "") -> Found | None:
    kind = kind_of(text)
    if kind is None:
        return None
    match = YEAR.search(text)
    year = int(match.group(1) or match.group(2)) if match else None
    numbers = {
        n for n in (intervat.normalize_number(m) for m in intervat.NUMBER.findall(text)) if n
    }
    numbers.discard(intervat.normalize_number(cabinet_number or ""))
    found: list[Client] = []
    if numbers:
        found = list(clients.filter(enterprise_number__in=numbers)[:3])
    if not found:
        nationals = _national_numbers(text)
        if nationals:
            found = list(clients.filter(kind=Client.Kind.PERSON, national_number__in=nationals)[:3])
    return Found(kind, year, found)


def title(found: Found) -> str:
    return f"{found.kind.label}{f' — exercice {found.year}' if found.year else ''}"


def folder(found: Found, client: Client) -> str:
    return found.kind.folder_person if client.is_person else found.kind.folder_entity
