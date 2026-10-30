"""Documents du SPF Finances déposés dans « Déposer des documents » : reconnus et classés (D-084).

Complète le dépôt unique (D-041), qui reconnaît déjà les déclarations TVA d'Intervat (XML et
PDF) et les cartes d'identité. Ici : les autres courriers et documents du SPF —
avertissements-extraits de rôle (IPP, ISOC, IPM), accusés de réception Biztax et Tax-on-web,
listing clients annuel, avis de rectification, demandes de renseignements, versements
anticipés, compte courant TVA ; et, appris sur de vrais documents anonymisés (D-098) : la
procuration du cabinet, la copie de la déclaration IPP, les comptes annuels PDF de la BNB.

Comment :
1. le texte du PDF (pdftotext ; pour un courrier scanné sans texte, lecture de la 1re page sur
   le serveur) ;
2. le **type** par des mots sûrs (« avertissement-extrait de rôle » + « impôt des sociétés »…) ;
   aucun type sûr → rien n'est deviné ;
3. le **dossier** par le numéro d'entreprise ou le numéro national imprimé (contrôles
   modulo 97), parmi les dossiers visibles de la personne qui dépose ; le numéro du cabinet
   est ignoré ; si plusieurs dossiers sont cités, c'est le premier cité (le destinataire)
   (D-096) ; le numéro national ne sert qu'à la recherche (jamais gardé, affiché ni
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
    case: str = ""  # case de l'onglet Documents (au lieu d'une archive), si le dossier l'a
    doc_type: str = ""
    person_first: bool = False  # document d'un particulier : le numéro national d'abord
    year: re.Pattern[str] | None = None  # où lire l'exercice, si ce n'est pas « exercice d'imp. »
    # Case de dépôt de l'onglet Clôture cochée par ce document (D-114), et décalage entre
    # l'année lue et l'année de fin de l'exercice (exercice d'imposition N → exercice N-1).
    deposit: str = ""
    year_offset: int = 0


AER = ("avertissement-extrait de role", "avertissement extrait de role", "aanslagbiljet")
# Comptes annuels (modèle BNB) : « …exercice couvrant la période du 01/01/2020 au 31/12/2020 ».
ACCOUNTS_YEAR = re.compile(
    r"couvrant\s+la\s+p[ée]riode\s+du.{0,160}?au\s*\d{0,2}\s*/\s*\d{0,2}\s*/\s*(20\d{2})"
    r"|periode\s+van.{0,160}?tot\s*\d{0,2}\s*/\s*\d{0,2}\s*/\s*(20\d{2})",
    re.I | re.S,
)
# PV d'AG : « … l'exercice clôturé le 31/12/2025 ».
AG_YEAR = re.compile(
    r"exercice[^\n]{0,80}?cl[ôo]tur[ée]\w*\s+(?:le|au)\s+\d{1,2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*(20\d{2})"
    r"|boekjaar[^\n]{0,80}?afgesloten\s+op\s+\d{1,2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*(20\d{2})",
    re.I,
)
# Belcotax : « année de revenus 2025 ».
INCOME_YEAR = re.compile(
    r"ann[ée]e\s+de\s+revenus?\s*:?\s*(20\d{2})|inkomstenjaar\s*:?\s*(20\d{2})", re.I
)
# Listing clients : « Listing clients 2025 », « année civile 2025 » (D-115).
LISTING_YEAR = re.compile(
    r"(?:listing|liste annuelle|jaarlijkse lijst|klantenlisting)[^\n]{0,60}?(20\d{2})"
    r"|ann[ée]e\s+civile\s*:?\s*(20\d{2})|kalenderjaar\s*:?\s*(20\d{2})",
    re.I,
)
KINDS: tuple[Kind, ...] = (
    # Documents entiers qui citent beaucoup d'autres mots (« demandes de renseignements »,
    # « versements anticipés », « TVA »…) : reconnus en premier (vrais documents, D-098).
    # Procuration générale donnée au cabinet (modèle FID-Manager) → case « Procuration ».
    Kind("procuration", "Procuration fiscale et administrative",
         (("procuration", "volmacht"), ("mandant", "lastgever", "volmachtgever"),
          ("mandataire", "lasthebber", "volmachthebber")),
         "administratif", "administratif", case="procuration", doc_type="procuration"),
    # Documents signés renvoyés par le client (dossier de test 3, D-101).
    Kind("lettre_mission", "Lettre de mission",
         (("lettre de mission", "opdrachtbrief", "opdrachtovereenkomst"),
          ("honoraires", "erelonen", "objet de la mission", "voorwerp van de opdracht")),
         "administratif", "administratif", case="lettre-de-mission", doc_type="lettre_mission"),
    Kind("declaration_ubo", "Déclaration des bénéficiaires effectifs",
         (("declaration des beneficiaires effectifs",
           "verklaring van de uiteindelijke begunstigden"),
          ("soussigne", "declare", "ondergetekende", "verklaar")),
         "administratif", "administratif", case="declaration-ubo", doc_type="declaration_ubo"),
    # Copie de la déclaration IPP (Tax-on-web / MyMinfin) ou document préparatoire.
    Kind("declaration_ipp", "Déclaration IPP",
         (("declaration a l'impot des personnes physiques",
           "aangifte in de personenbelasting"),
          ("copie de votre declaration", "document preparatoire", "kopie van uw aangifte",
           "voorbereidend document")),
         "ipp", "ipp", person_first=True),
    # Comptes annuels au modèle de la Banque Nationale (PDF).
    Kind("comptes_annuels", "Comptes annuels (PDF)",
         (("comptes annuels", "jaarrekening"),
          ("deposer en vertu du code des societes", "code des societes et des associations",
           "neer te leggen krachtens het wetboek", "wetboek van vennootschappen en verenigingen")),
         "", "comptes", year=ACCOUNTS_YEAR, deposit="bnb"),
    # Procès-verbal de l'assemblée générale qui approuve les comptes → case « AG » (D-114).
    Kind("pv_ag", "Procès-verbal de l'assemblée générale",
         (("proces-verbal", "proces verbal", "notulen"),
          ("assemblee generale", "algemene vergadering"),
          ("comptes annuels", "jaarrekening")),
         "", "legal", year=AG_YEAR, deposit="ag"),
    # Accusé Belcotax des fiches 281.20 (rémunérations de dirigeants) → case « Fiches 281 »
    # (D-115).
    Kind("belcotax_28120", "Fiches 281.20 — Belcotax",
         (("belcotax",), ("281.20", "281,20", "325.20", "325,20")),
         "", "isoc", year=INCOME_YEAR, deposit="28120"),
    # Accusé Belcotax des fiches 281.50 (honoraires, commissions) → case « 281.50 » (D-114).
    Kind("belcotax_28150", "Fiches 281.50 — Belcotax",
         (("belcotax",), ("281.50", "281,50", "325.50", "325,50")),
         "", "isoc", year=INCOME_YEAR, deposit="28150"),
    Kind("aer_isoc", "Avertissement-extrait de rôle ISOC",
         (AER, ("des societes", "vennootschapsbelasting")), "isoc", "isoc"),
    Kind("aer_ipm", "Avertissement-extrait de rôle IPM",
         (AER, ("personnes morales", "rechtspersonenbelasting")), "isoc", "isoc"),
    Kind("aer_ipp", "Avertissement-extrait de rôle IPP",
         (AER, ("personnes physiques", "personenbelasting")), "ipp", "ipp", person_first=True),
    Kind("biztax", "Biztax — accusé de réception de la déclaration",
         (("biztax",), ("accuse de reception", "ontvangstbewijs", "bien ete deposee",
                        "bien ete enregistree", "a ete deposee")), "isoc", "isoc",
         deposit="isoc", year_offset=-1),
    # Annexes 270 de la déclaration (270 MLH : loyers) → case « Annexes 270 » (D-114). Après
    # l'accusé Biztax, qui peut citer les annexes jointes.
    Kind("annexe_270", "Annexe 270",
         (("270 mlh", "270mlh", "annexe 270", "bijlage 270", "modele 270", "model 270",
           "formulaire 270", "formulier 270"),),
         "", "isoc", deposit="270", year_offset=-1),
    Kind("tax_on_web", "Tax-on-web — accusé de réception de la déclaration IPP",
         (("tax-on-web", "taxonweb", "myminfin"), ("accuse de reception", "ontvangstbewijs"),
          ("impot des personnes physiques", "personenbelasting", "declaration ipp")),
         "ipp", "ipp", person_first=True),
    Kind("listing_clients", "Listing clients annuel (TVA)",
         (("listing annuel", "listing des clients", "klantenlisting", "jaarlijkse lijst"),
          ("assujetti", "btw-plichtige", "tva", "btw")), "tva", "tva",
         year=LISTING_YEAR, deposit="listing"),
    Kind("compte_tva", "Compte courant TVA",
         (("compte courant tva", "compte-courant tva", "btw-rekening-courant"),), "tva", "tva"),
    Kind("rectification", "Avis de rectification de la déclaration",
         (("avis de rectification", "bericht van wijziging"),), "ipp", "isoc", action=True),
    Kind("renseignements", "Demande de renseignements",
         (("demande de renseignements", "vraag om inlichtingen"),), "ipp", "isoc", action=True),
    Kind("versements_anticipes", "Versements anticipés",
         (("versements anticipes", "versement anticipe", "voorafbetaling"),
          ("avis", "rappel", "aperçu", "apercu", "decompte", "overzicht")), "ipp", "isoc"),
    # Extrait du registre UBO (MyMinfin) → case UBO de la société (D-097).
    Kind("extrait_ubo", "Extrait du registre UBO",
         (("registre des beneficiaires effectifs", "registre ubo", "ubo-register",
           "register van de uiteindelijke begunstigden"),
          ("extrait", "uittreksel", "informations relatives aux beneficiaires effectifs",
           "informatie over de uiteindelijke begunstigden")),
         "administratif", "administratif", case="ubo", doc_type="extrait_ubo"),
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
    match = (kind.year or YEAR).search(text)
    digits = next((g for g in match.groups() if g), None) if match else None
    year = int(digits) if digits else None
    cabinet = intervat.normalize_number(cabinet_number or "")
    # Dans l'ordre du document : le destinataire (déclarant) est toujours cité en premier ; un
    # listing clients cite ensuite les numéros de ses clients (grand test, D-096).
    cited = (intervat.normalize_number(m) for m in intervat.NUMBER.findall(text))
    ordered = [n for n in dict.fromkeys(cited) if n and n != cabinet]
    found: list[Client] = []
    nationals = _national_numbers(text)
    if kind.person_first and nationals:
        # Déclaration d'un particulier : elle peut citer l'entreprise d'un employeur, client
        # lui aussi ; le numéro national désigne le bon dossier.
        persons = clients.filter(kind=Client.Kind.PERSON, national_number__in=nationals)
        found = list(persons[:3])
        if found:
            return Found(kind, year, found)
    if ordered:
        known = {c.enterprise_number: c for c in clients.filter(enterprise_number__in=ordered)}
        first = next((known[n] for n in ordered if n in known), None)
        found = [first] if first is not None else []
    if not found and nationals:
        found = list(clients.filter(kind=Client.Kind.PERSON, national_number__in=nationals)[:3])
    return Found(kind, year, found)


def title(found: Found) -> str:
    if not found.year:
        return found.kind.label
    civil = found.kind.year in (INCOME_YEAR, LISTING_YEAR)  # année civile, pas un exercice
    return f"{found.kind.label} — {'année' if civil else 'exercice'} {found.year}"


def folder(found: Found, client: Client) -> str:
    return found.kind.folder_person if client.is_person else found.kind.folder_entity
