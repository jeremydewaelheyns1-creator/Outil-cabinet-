"""Vrais documents officiels reconnus au dépôt (D-098).

Jeremy a fourni de vrais documents anonymisés (procuration FID-Manager, extrait UBO, comptes
annuels PDF et XBRL, déclaration Biztax, copie de déclaration IPP). Ils ne sont PAS dans le
dépôt : on n'en a gardé que la structure. Ici, des copies entièrement fictives qui reprennent
cette structure (mêmes titres, mêmes balises, mêmes pièges : une procuration cite « TVA »,
« demandes de renseignements » et « versements anticipés » ; une déclaration IPP cite
l'entreprise de l'employeur…).
"""

from __future__ import annotations

import base64
import shutil

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.models import AccessLog, CabinetSettings
from apps.core.testing.factories import ClientFactory, PersonFactory
from apps.core.testing.numbers import enterprise_number, national_number
from apps.documents import inbox, spf_docs, xbrl
from apps.documents.models import Document, InboxItem

pytestmark = pytest.mark.django_db
needs_poppler = pytest.mark.skipif(not shutil.which("pdftotext"), reason="poppler absent")


def dotted(seed: int) -> str:
    n = enterprise_number(seed)
    return f"{n[:4]}.{n[4:7]}.{n[7:]}"


def pdf(name: str, *paragraphs: str) -> SimpleUploadedFile:
    from weasyprint import HTML

    html = "".join(f"<p>{p}</p>" for p in paragraphs)
    return SimpleUploadedFile(name, HTML(string=html).write_pdf(), content_type="application/pdf")


def deposit(web, *files):
    return web.post(reverse("depot:index"), {"files": list(files)})


# --- Copies fictives des structures réelles -------------------------------------------------


def procuration_pdf(mandant: str, cabinet: str) -> SimpleUploadedFile:
    """Modèle FID-Manager : mandant (le client) d'abord, puis le cabinet mandataire."""
    return pdf(
        "procuration.pdf",
        "~FID-MANAGER-CONTEXT|[1,2,2,2026010001]|~",
        "Procuration fiscale et administrative générale. MANDAT",
        "Entre les soussignés,",
        f"Nom : Société Fictive SRL — Numéro d'entreprise : {mandant}",
        "ci-après dénommé(e) le « mandant »,",
        f"et, Nom : Cabinet Fictif SRL — Numéro d'entreprise : {cabinet}",
        "Expert-comptable et conseil fiscal. Ci-après dénommé(e) le « mandataire ».",
        "Signer et introduire toutes déclarations fiscales (TVA, impôt des sociétés, impôt des "
        "personnes physiques, etc.) ; déclaration périodique à la TVA ;",
        "Signer toute correspondance écrite (réponses aux demandes de renseignements, réponses "
        "aux avis de modification de déclaration, etc.) ; versements anticipés ;",
        "Effectuer et gérer le registre des bénéficiaires effectifs (UBO) ; extrait ;",
        "Déposer les comptes annuels auprès de la BNB ;",
    )


def ubo_extract_pdf(number: str) -> SimpleUploadedFile:
    """Mise en page réelle de MyMinfin (sans le mot « extrait » en titre)."""
    return pdf(
        "registre_ubo.pdf",
        "Informations relatives aux bénéficiaires effectifs (UBO) de SOCIÉTÉ FICTIVE",
        f"N°BCE ou identifiant: {number}",
        "Bénéficiaire effectif : FICTIF Jean — 100 %",
        "Cet extrait du Registre UBO reflète les données enregistrées à la date du jour.",
    )


def accounts_pdf(number: str, administrator: str = "") -> SimpleUploadedFile:
    """Modèle normalisé de la Banque Nationale (1re page)."""
    return pdf(
        "comptes.pdf",
        "COMPTES ANNUELS ET AUTRES DOCUMENTS À DÉPOSER EN VERTU DU CODE DES SOCIÉTÉS "
        "ET DES ASSOCIATIONS",
        "DONNÉES D'IDENTIFICATION (à la date du dépôt) DÉNOMINATION: SOCIÉTÉ FICTIVE",
        f"Numéro d'entreprise BE{number.replace('.', '')}",
        "COMPTES ANNUELS EN EUROS (2 décimales) approuvés par l'assemblée générale du 10/06/2026",
        "et relatifs à l'exercice couvrant la période du 01/01/2025 au 31/12/2025",
        "Exercice précédent du 01/01/2024 au 31/12/2024",
        f"LISTE DES ADMINISTRATEURS, GÉRANTS ET COMMISSAIRES : {administrator}",
        "Dettes fiscales, salariales et sociales — TVA à payer ; versements anticipés",
    )


def ipp_pdf(nn: str, employer: str) -> SimpleUploadedFile:
    """Copie de la déclaration IPP reçue par le SPF (document préparatoire)."""
    shown = f"{nn[:2]}.{nn[2:4]}.{nn[4:6]}-{nn[6:9]}.{nn[9:]}"
    return pdf(
        "ipp.pdf",
        f"Employeur : numéro d'entreprise {employer}",
        "Ceci est une copie de votre déclaration reçue par le SPF Finances "
        "(numéro de document : 12345678).",
        f"Numéro national (NN) : {shown}",
        "DOCUMENT PRÉPARATOIRE À LA DÉCLARATION À L'IMPÔT DES PERSONNES PHYSIQUES",
        "Exercice d'imposition 2026 - Revenus de l'année 2025",
        "l'administration fiscale vous versera les remboursements éventuels d'impôts sur les "
        "revenus, de précomptes et de versements anticipés. Demande de renseignements. TVA.",
    )


def accounts_xbrl(number: str) -> bytes:
    """Comptes annuels au format XBRL de la Banque Nationale (taxonomie pfs, modèle abrégé)."""
    ident = (
        '<xbrli:entity><xbrli:identifier scheme="http://www.fgov.be">'
        f"BE{number}</xbrli:identifier></xbrli:entity>"
    )

    def context(name: str, period: str) -> str:
        return f'<xbrli:context id="{name}">{ident}<xbrli:period>{period}</xbrli:period></xbrli:context>'  # noqa: E501

    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
        'xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'xmlns:pfs="http://www.nbb.be/be/fr/pfs/ci/2021-01-01" '
        'xmlns:pfs-gcd="http://www.nbb.be/be/fr/pfs/ci/gcd/2021-01-01">'
        '<link:schemaRef xlink:type="simple" '
        'xlink:href="http://www.nbb.be/be/fr/pfs/ci/abbreviated/pfs-abbr-2021-01-01.xsd"/>'
        + context("CurrentInstant", "<xbrli:instant>2025-12-31</xbrli:instant>")
        + context(
            "CurrentDuration",
            "<xbrli:startDate>2025-01-01</xbrli:startDate>"
            "<xbrli:endDate>2025-12-31</xbrli:endDate>",
        )
        + context("PrecedingInstant", "<xbrli:instant>2024-12-31</xbrli:instant>")
        + context(
            "PrecedingDuration",
            "<xbrli:startDate>2024-01-01</xbrli:startDate>"
            "<xbrli:endDate>2024-12-31</xbrli:endDate>",
        )
        + '<pfs-gcd:DocumentIdentifier contextRef="CurrentDuration">Comptes annuels'
        "</pfs-gcd:DocumentIdentifier>"
        '<pfs-gcd:EntityCurrentLegalName contextRef="CurrentDuration">SOCIÉTÉ FICTIVE'
        "</pfs-gcd:EntityCurrentLegalName>"
        '<pfs-gcd:AccountsApprovalDateGeneralAssembly contextRef="CurrentInstant">2026-06-10'
        "</pfs-gcd:AccountsApprovalDateGeneralAssembly>"
        '<pfs:Assets contextRef="CurrentInstant" unitRef="EUR" decimals="2">368296.86</pfs:Assets>'
        '<pfs:Assets contextRef="PrecedingInstant" unitRef="EUR" decimals="2">1.00</pfs:Assets>'
        '<pfs:Equity contextRef="CurrentInstant" unitRef="EUR" decimals="2">55000.00</pfs:Equity>'
        '<pfs:GainLossPeriod contextRef="CurrentDuration" unitRef="EUR" decimals="2">95167.82'
        "</pfs:GainLossPeriod>"
        '<pfs:GainLossPeriod contextRef="PrecedingDuration" unitRef="EUR" decimals="2">-20394.36'
        "</pfs:GainLossPeriod>"
        "</xbrli:xbrl>"
    ).encode()


def biztax(number: str, annex: bytes = b"%PDF-1.4 annexe fictive") -> bytes:
    """Déclaration Biztax : <biztax><xbrl>, taxonomie du SPF, annexes PDF intégrées."""
    ident = f'<entity><identifier scheme="http://www.fgov.be">BE{number}</identifier></entity>'
    origin = (
        '<scenario><xbrldi:explicitMember dimension="d-origin:OriginDimension">'
        "d-origin:BelgiumMember</xbrldi:explicitMember></scenario>"
    )
    return (
        "<?xml version='1.0' encoding='UTF-8'?><biztax>"
        '<xbrl xmlns="http://www.xbrl.org/2003/instance" '
        'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
        'xmlns:pfs-gcd="http://www.nbb.be/be/fr/pfs/ci/gcd/2022-04-01" '
        'xmlns:tax-inc="http://www.minfin.fgov.be/be/tax/inc/2022-04-30" '
        'xmlns:d-origin="http://www.minfin.fgov.be/be/tax/d/origin/2022-04-30">'
        f'<context id="D0">{ident}<period><startDate>2025-01-01</startDate>'
        "<endDate>2025-12-31</endDate></period></context>"
        f'<context id="I1">{ident}<period><instant>2025-12-31</instant></period></context>'
        f'<context id="Belgium">{ident}<period><startDate>2025-01-01</startDate>'
        f"<endDate>2025-12-31</endDate></period>{origin}</context>"
        '<tax-inc:TaxReturnType contextRef="D0">VenB</tax-inc:TaxReturnType>'
        '<tax-inc:AssessmentYear contextRef="D0">2026</tax-inc:AssessmentYear>'
        '<tax-inc:FiscalResult contextRef="D0" unitRef="EUR" decimals="2">127853.02'
        "</tax-inc:FiscalResult>"
        '<tax-inc:FiscalResult contextRef="Belgium" unitRef="EUR" decimals="2">1.00'
        "</tax-inc:FiscalResult>"
        '<tax-inc:Prepayments contextRef="D0" unitRef="EUR" decimals="2">15000.00'
        "</tax-inc:Prepayments>"
        f'<tax-inc:OtherDocuments contextRef="D0">{base64.b64encode(annex).decode()}'
        "</tax-inc:OtherDocuments>"
        '<pfs-gcd:EntityCurrentLegalName contextRef="D0">SOCIÉTÉ FICTIVE'
        "</pfs-gcd:EntityCurrentLegalName>"
        "</xbrl></biztax>"
    ).encode()


def xbrl_upload(name: str, content: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type="application/octet-stream")


# --- PDF : les pièges des vrais documents ---------------------------------------------------


@needs_poppler
def test_procuration_goes_to_its_case_not_to_vat_nor_to_be_answered(web):
    company = ClientFactory(enterprise_number=enterprise_number(8001))
    CabinetSettings.objects.update_or_create(pk=1, defaults={"enterprise_number": dotted(8002)})
    response = deposit(web, procuration_pdf(dotted(8001), dotted(8002)))
    assert response.status_code in (200, 302)
    document = Document.objects.get(client=company)
    assert (document.case, document.doc_type) == ("procuration", "procuration")
    assert document.title == "Procuration fiscale et administrative"
    assert not document.review_needed  # pas pris pour une demande de renseignements
    assert not company.vat_filings.exists()  # pas pris pour une déclaration TVA
    assert not InboxItem.objects.exists()


@needs_poppler
def test_procuration_of_a_person_is_found_by_national_number(web):
    nn = national_number(41, "790203")
    person = PersonFactory(national_number=nn)
    shown = f"{nn[:2]}.{nn[2:4]}.{nn[4:6]}-{nn[6:9]}.{nn[9:]}"
    upload = pdf("procuration.pdf", "Procuration fiscale et administrative générale.",
                 f"Nom : FICTIF Paul — numéro national {shown} — le « mandant »",
                 "et le cabinet, le « mandataire ».")  # fmt: skip
    deposit(web, upload)
    document = Document.objects.get(client=person)
    assert document.case == "procuration"


@needs_poppler
def test_real_ubo_layout_is_recognised(web):
    company = ClientFactory(enterprise_number=enterprise_number(8011))
    deposit(web, ubo_extract_pdf(enterprise_number(8011)))
    document = Document.objects.get(client=company)
    assert (document.case, document.doc_type) == ("ubo", "extrait_ubo")


@needs_poppler
def test_accounts_pdf_goes_to_the_annual_accounts_page(web):
    company = ClientFactory(enterprise_number=enterprise_number(8021))
    # Un administrateur (société) cité ensuite, client lui aussi : pas lui le destinataire.
    ClientFactory(enterprise_number=enterprise_number(8022), name="Administrateur Fictif")
    deposit(web, accounts_pdf(dotted(8021), administrator=f"SRL FICTIVE {dotted(8022)}"))
    document = Document.objects.get()
    assert document.client == company and document.folder == "comptes" and not document.case
    assert document.title == "Comptes annuels (PDF) — exercice 2025"
    page = web.get(reverse("clients:annual_accounts", args=[company.pk])).content.decode()
    assert "Comptes déposés au cabinet" in page and document.title in page
    assert "?annee=2025" in page  # rangé par année comme les autres archives


@needs_poppler
def test_accounts_pdf_for_a_person_waits_with_the_reason(web):
    nn = national_number(42, "790203")
    PersonFactory(national_number=nn)
    upload = pdf("comptes.pdf", "Comptes annuels et autres documents à déposer en vertu du "
                 "Code des sociétés et des associations",
                 f"NN {nn[:2]}.{nn[2:4]}.{nn[4:6]}-{nn[6:9]}.{nn[9:]}")  # fmt: skip
    deposit(web, upload)
    item = InboxItem.objects.get()
    assert "Comptes annuels" in item.reason and "personne physique" in item.reason
    assert nn not in item.reason


@needs_poppler
def test_ipp_declaration_goes_to_the_person_not_to_the_employer(web):
    nn = national_number(43, "880512")
    person = PersonFactory(national_number=nn)
    employer = ClientFactory(enterprise_number=enterprise_number(8031), name="Employeur Fictif")
    response = deposit(web, ipp_pdf(nn, dotted(8031)))
    document = Document.objects.get()
    assert document.client == person and document.folder == "ipp"
    assert document.title == "Déclaration IPP — exercice 2026"
    assert not employer.documents.exists() and not document.review_needed
    # Le numéro national ne s'affiche ni dans le titre ni dans la réponse.
    assert nn not in document.title and nn not in response.content.decode()


def test_kinds_on_texts_shaped_like_the_real_ones():
    """Textes bruts comme pdftotext les sort des vrais documents (mise en page incluse)."""
    accounts = (
        "COMPTES ANNUELS ET AUTRES DOCUMENTS À\n   DÉPOSER EN VERTU DU CODE DES SOCIÉTÉS\n"
        "  ET DES ASSOCIATIONS\n et relatifs à l'exercice couvrant la période du      "
        "/     /      au     /12   /2020\n Exercice précédent du / / au 31 /12 /2019"
    )
    found = spf_docs.kind_of(accounts)
    assert found is not None and found.slug == "comptes_annuels"
    assert spf_docs.identify(accounts, ClientFactory._meta.model.objects.none()).year == 2020
    ipp = ("DOCUMENT PRÉPARATOIRE\n   À LA DÉCLARATION À L'IMPÔT DES PERSONNES PHYSIQUES\n"
           "Exercice d'imposition 2026 - Revenus de l'année 2025")  # fmt: skip
    assert spf_docs.kind_of(ipp).slug == "declaration_ipp"
    # Un avertissement-extrait de rôle IPP reste un avertissement-extrait de rôle.
    aer = "Avertissement-extrait de rôle — impôt des personnes physiques — exercice 2026"
    assert spf_docs.kind_of(aer).slug == "aer_ipp"


# --- XBRL : comptes annuels (BNB) et Biztax -------------------------------------------------


def test_accounts_xbrl_is_read():
    filing = xbrl.read(accounts_xbrl(enterprise_number(8041)))
    assert filing is not None and filing.kind == xbrl.ACCOUNTS
    assert filing.enterprise_number == enterprise_number(8041)
    assert filing.title == "Comptes annuels (XBRL) — exercice clôturé le 31/12/2025"
    assert filing.model == "abrégé" and str(filing.approved_on) == "2026-06-10"
    figures = dict(filing.figures)
    assert str(figures["Total du bilan"]) == "368296.86"  # l'exercice, pas le précédent
    assert str(figures["Bénéfice (perte) de l'exercice"]) == "95167.82"


def test_biztax_is_read():
    filing = xbrl.read(biztax(enterprise_number(8042)))
    assert filing is not None and filing.kind == xbrl.BIZTAX
    assert filing.title == "Déclaration ISOC Biztax (XBRL) — exercice d'imposition 2026"
    assert str(dict(filing.figures)["Résultat fiscal"]) == "127853.02"  # pas la dimension
    assert filing.annexes == ["Autres documents"]
    assert filing.period == "du 01/01/2025 au 31/12/2025"


def test_other_xml_and_dangerous_xml_are_not_taken():
    assert xbrl.read(b"<?xml version='1.0'?><VATConsignment/>") is None
    assert xbrl.read(b"pas du xml") is None
    bomb = (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
            b"<biztax><xbrl>&e;</xbrl></biztax>")  # fmt: skip
    assert xbrl.read(bomb) is None
    # XBRL sans numéro d'entreprise : rien n'est deviné.
    assert xbrl.read(accounts_xbrl(enterprise_number(8043)).replace(b"fgov.be", b"x.org")) is None


def test_accounts_xbrl_deposit_preview_and_place(web, user):
    company = ClientFactory(enterprise_number=enterprise_number(8051))
    deposit(web, xbrl_upload("comptes_2025.xbrl", accounts_xbrl(enterprise_number(8051))))
    document = Document.objects.get(client=company)
    assert document.folder == "comptes" and document.content_type == "application/xml"
    page = web.get(reverse("clients:annual_accounts", args=[company.pk])).content.decode()
    assert "Comptes annuels (XBRL)" in page
    url = reverse("clients:document_viewer", args=[company.pk, document.pk])
    html = web.get(url, HTTP_HX_REQUEST="true").content.decode()
    assert "Comptes annuels (modèle abrégé)" in html and "368\u202f296,86" in html
    assert "10/06/2026" in html and "Pas d'aperçu" not in html
    assert "Archives › Comptes annuels (BNB)" in html
    assert "SOCIÉTÉ FICTIVE" not in html  # aucun nom repris dans l'aperçu
    assert AccessLog.objects.filter(object_id=str(document.pk)).exists()


def test_biztax_deposit_goes_to_isoc(web):
    company = ClientFactory(enterprise_number=enterprise_number(8061))
    deposit(web, xbrl_upload("isoc_2026.biztax", biztax(enterprise_number(8061))))
    document = Document.objects.get(client=company)
    assert document.folder == "isoc"
    page = web.get(reverse("clients:archives", args=[company.pk])).content.decode()
    assert "Déclaration ISOC Biztax" in page and 'id="annee-2026-isoc"' in page
    url = reverse("clients:document_viewer", args=[company.pk, document.pk])
    html = web.get(url, HTTP_HX_REQUEST="true").content.decode()
    assert "Résultat fiscal" in html and "127\u202f853,02" in html
    assert "Annexes jointes : Autres documents." in html


def test_xbrl_with_unknown_number_waits_and_a_broken_one_is_refused(web):
    deposit(web, xbrl_upload("autre.xbrl", accounts_xbrl(enterprise_number(8999))))
    item = InboxItem.objects.get()
    assert "Comptes annuels" in item.reason and "aucun dossier" in item.reason
    broken = xbrl_upload("faux.biztax", b"%PDF-1.4 pas un biztax")
    response = web.post(reverse("depot:index") + "?panneau=1", {"files": [broken]})
    assert "Format non accepté" in response.content.decode()
    assert InboxItem.objects.count() == 1 and not Document.objects.exists()


def test_xbrl_of_a_hidden_dossier_is_not_filed(web):
    from apps.core.testing.factories import PortfolioFactory

    ClientFactory(enterprise_number=enterprise_number(8071),
                  portfolio=PortfolioFactory(is_private=True))  # fmt: skip
    deposit(web, xbrl_upload("c.xbrl", accounts_xbrl(enterprise_number(8071))))
    assert not Document.objects.exists()
    assert "aucun dossier" in InboxItem.objects.get().reason


# --- Rangement à la main, dépôt sur la page, suppression ------------------------------------


def test_annual_accounts_is_a_place_for_companies_only():
    company, person = ClientFactory(), PersonFactory()
    assert ("folder:comptes", "Archives › Comptes annuels (BNB)") in inbox.places(company)
    assert all(value != "folder:comptes" for value, _ in inbox.places(person))


def test_upload_on_the_page_then_delete_returns_to_the_page(web):
    company = ClientFactory(enterprise_number=enterprise_number(8081))
    url = reverse("clients:archives", args=[company.pk]) + "?sujet=comptes"  # D-105
    upload = SimpleUploadedFile("c.pdf", b"%PDF-1.4 fictif", content_type="application/pdf")
    web.post(reverse("clients:document_upload", args=[company.pk]),
             {"file": upload, "title": "Comptes annuels 2024", "folder": "comptes",
              "retour": url})  # fmt: skip
    document = Document.objects.get(client=company)
    assert document.folder == "comptes"
    assert "Comptes annuels 2024" in web.get(url).content.decode()
    # Toujours visibles aussi sur la page des comptes déposés à la Banque Nationale.
    accounts = reverse("clients:annual_accounts", args=[company.pk])
    assert "Comptes annuels 2024" in web.get(accounts).content.decode()
    delete = reverse("clients:document_delete", args=[company.pk, document.pk])
    response = web.post(delete, {"confirme": "1"})
    assert response.status_code == 302 and response["Location"] == url


def test_mail_attachment_is_described():
    from apps.mailbox.recognize import recognize

    clients = ClientFactory._meta.model.objects.none()
    kind, label = recognize("isoc.biztax", biztax(enterprise_number(8091)),
                            "application/xml", clients)  # fmt: skip
    assert (kind, label) == ("impot", "Déclaration ISOC Biztax")
    _, label = recognize("c.xbrl", accounts_xbrl(enterprise_number(8091)), "application/xml",
                         clients)  # fmt: skip
    assert label == "Comptes annuels (XBRL)"


# --- Pièces signées renvoyées par le client (dossier de test 3, D-101) ----------------------


@needs_poppler
def test_signed_engagement_letter_is_not_a_vat_return(web):
    company = ClientFactory(enterprise_number=enterprise_number(8101))
    letter = pdf("lettre.pdf", "Lettre de mission",
                 f"Client : Société Fictive SRL — numéro d'entreprise {dotted(8101)}",
                 "1. Objet de la mission : comptabilité, déclarations à l'impôt des sociétés.",
                 "3. Honoraires : 2 400,00 EUR hors TVA, facturés chaque trimestre.")  # fmt: skip
    deposit(web, letter)
    document = Document.objects.get(client=company)
    assert (document.case, document.doc_type) == ("lettre-de-mission", "lettre_mission")
    assert not company.vat_filings.exists()


@needs_poppler
def test_signed_ubo_declaration_goes_to_its_case(web):
    company = ClientFactory(enterprise_number=enterprise_number(8102))
    declaration = pdf("ubo.pdf", "Déclaration des bénéficiaires effectifs",
                      f"Je soussigné, gérant de Société Fictive SRL ({dotted(8102)}), déclare que "
                      "les bénéficiaires effectifs sont : FICTIF Jean, 100 %.")  # fmt: skip
    deposit(web, declaration)
    document = Document.objects.get(client=company)
    assert (document.case, document.doc_type) == ("declaration-ubo", "declaration_ubo")


def test_vat_title_is_needed_not_just_the_words():
    from apps.vat import intervat

    assert not intervat.VAT_TITLE.search(
        "honoraires hors tva ; déclarations à l'impôt des sociétés"
    )
    titles = ("déclaration périodique à la tva", "déclaration tva", "listing intracommunautaire",
              "periodieke btw-aangifte", "relevé intracommunautaire")  # fmt: skip
    for title in titles:
        assert intervat.VAT_TITLE.search(title)


def test_card_reading_needs_a_name_line():
    from apps.documents import mrz

    lines = mrz.build_td1(document_number="592417306582", surname="FICTIF", given_names="PAUL",
                          birth="650923", expiry="310314", sex="M")  # fmt: skip
    good = mrz.parse_td1(lines)
    assert good.valid and good.name_readable
    # La 1re ligne relue à la place du nom : les contrôles passent, mais le nom est illisible.
    bad = mrz.parse_td1([lines[0], lines[1], lines[0]])
    assert bad.valid and not bad.name_readable
