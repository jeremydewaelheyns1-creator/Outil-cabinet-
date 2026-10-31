"""Un modèle tiré d'un document déjà rempli (D-124). Tout est fictif."""

from __future__ import annotations

import io
from datetime import date

import pytest
from django.urls import reverse
from docx import Document as Word

from apps.clients.models import Relation
from apps.core.testing.factories import ClientFactory, PersonFactory
from apps.documents import from_example, letter
from apps.documents.models import LetterTemplate

pytestmark = pytest.mark.django_db


def filled_pv() -> bytes:
    d = Word()
    d.add_paragraph("Menuiserie Fictive SRL")
    d.add_paragraph("Rue des Essais 12")
    d.add_paragraph("5000 Namur")
    d.add_paragraph("BCE : BE 0987.654.394")
    d.add_paragraph("Procès-verbal de l'assemblée générale ordinaire du 30/06/2026")
    d.add_paragraph("La séance est ouverte à 18h00 sous la présidence de Paul Testeur, gérant.")
    d.add_paragraph("Associés présents : Paul Testeur (60 parts) et Marie Essai (40 parts).")
    d.add_paragraph("L'assemblée approuve les comptes annuels arrêtés au 31/12/2025, bénéfice de "
                    "32.174,60 €.")  # fmt: skip
    d.add_paragraph("Le bénéfice est reporté. Contact : paul@menuiserie-fictive.example")
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Impôts", "8.930,00"
    d.add_paragraph("La séance est levée à 18h30.")
    d.add_paragraph("Fait à Namur, le 30 juin 2026.")
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


@pytest.fixture
def example_client():
    from apps.closing import services

    company = ClientFactory(name="Menuiserie Fictive", legal_form="SRL",
                            enterprise_number="0987654394", street="Rue des Essais 12",
                            postal_code="5000", city="Namur", fiscal_year_end_month=12,
                            fiscal_year_end_day=31)  # fmt: skip
    manager = PersonFactory(name="Testeur", first_name="Paul")
    partner = PersonFactory(name="Essai", first_name="Marie")
    Relation.objects.create(entity=company, person=manager, role=Relation.Role.MANAGER)
    Relation.objects.create(entity=company, person=manager, role=Relation.Role.SHAREHOLDER)
    Relation.objects.create(entity=company, person=partner, role=Relation.Role.SHAREHOLDER)
    services.ensure_years(company, date(2026, 10, 30))
    return company


def test_everything_of_the_client_becomes_a_hole(example_client):
    result = from_example.convert(filled_pv(), example_client)
    text = from_example.text_of(result.content)
    for leftover in ("Menuiserie Fictive", "Essais 12", "Namur", "0987", "Paul Testeur",
                     "Marie Essai", "30/06/2026", "18h00", "18h30", "31/12/2025", "32.174,60",
                     "8.930,00", "paul@", "30 juin 2026"):  # fmt: skip
        assert leftover not in text, leftover
    assert "Procès-verbal de l'assemblée générale ordinaire" in text  # le texte du cabinet reste
    report = dict(result.report())
    assert report["nom du client"] >= 1 and report["montant"] == 2 and report["heure"] == 2
    holes = from_example.holes_for(result.content, "pv_ag")
    fields = [v["field"] for v in holes.values()]
    for code in ("client.denomination", "client.adresse", "client.localite", "client.numero",
                 "client.representant", "exercice.cloture", "ag.date", "ag.debut", "ag.fin",
                 "demander"):  # fmt: skip
        assert code in fields, code


def test_upload_a_filled_document_and_reuse_it_for_another_client(client, make_user,
                                                                   example_client):  # fmt: skip
    from django.core.files.uploadedfile import SimpleUploadedFile

    admin = make_user(is_staff=True, capabilities=["clients.edit"])
    client.force_login(admin)
    upload = SimpleUploadedFile("pv-menuiserie.docx", filled_pv())
    # Aucun client à choisir : retrouvé par le numéro d'entreprise imprimé.
    response = client.post(reverse("lettre:models"), {"sorte": "pv_ag", "modele": upload})
    template = LetterTemplate.objects.get()
    assert response.status_code == 302 and template.kind == "pv_ag" and not template.active
    assert template.origin["exemple"] and "Menuiserie" not in str(template.origin)
    page = client.get(reverse("lettre:model", args=[template.pk])).content.decode()
    assert "Modèle tiré d'un document rempli" in page
    listing = client.get(reverse("lettre:models") + "?sorte=pv_ag").content.decode()
    assert "vide ou déjà rempli" in listing and "Fait pour le client" not in listing
    assert client.get(reverse("lettre:download", args=[template.pk])).status_code == 200
    # Réutilisé pour un autre client : son nom apparaît, plus rien de la Menuiserie.
    other = ClientFactory(name="Garage Autre", legal_form="SRL", street="Avenue B 3",
                          postal_code="4000", city="Liège")  # fmt: skip
    answers = {k: "1,00" for k, _ in letter.questions(template)}
    ctx = {"date": "15/06/2027", "debut": "17h00", "fin": "17h45", "exercice_fin": "31/12/2026",
           "dividende": "non"}  # fmt: skip
    text = from_example.text_of(letter.fill(template, other, answers, ctx))
    assert "Garage Autre" in text and "Avenue B 3" in text and "17h45" in text
    assert "Menuiserie" not in text and "Namur" not in text and "Testeur" not in text


def test_without_knowing_the_client_the_shape_is_enough():
    """Client inconnu de l'outil : la forme suffit (société, numéro, localité, dates, heures,
    montants) ; l'assistant IA trouve les noms de personnes."""
    result = from_example.convert(filled_pv(), None)
    text = from_example.text_of(result.content)
    for leftover in ("Menuiserie Fictive SRL", "0987", "5000 Namur", "30/06/2026", "18h00",
                     "32.174,60", "paul@"):  # fmt: skip
        assert leftover not in text, leftover
    holes = from_example.holes_for(result.content, "pv_ag")
    assert "exercice.cloture" in [v["field"] for v in holes.values()]  # « arrêtés au … »


def realistic_pv() -> bytes:
    """Mise en page d'un vrai PV de cabinet (valeurs inventées) : nom puis forme sur deux
    lignes, « boîte », année en lettres, « Monsieur … », tableaux de montants."""
    d = Word()
    for line in ("TESTFICT", "S.R.L.", "Rue des Essais 11 boîte 2", "1150 – Woluwé-Saint-Pierre",
                 "R.P.M. 0987.654.394"):  # fmt: skip
        d.add_paragraph(line)
    d.add_paragraph("L’an deux mille vingt-six le 23 septembre, s’est tenue l’assemblée générale.")
    d.add_paragraph("La séance est ouverte à 18h00 sous la présidence de Monsieur Fictif.")
    d.add_paragraph("Mr Jean Fictif 100")
    d.add_paragraph("L’assemblée approuve les comptes annuels arrêtés au 31/12/2025.")
    t = d.add_table(rows=0, cols=4)
    for label, value in (("- Bénéfice d’exploitation", "42.310,00"), ("- ATN Auto", "2.140,00")):
        c = t.add_row().cells
        c[0].text, c[1].text, c[2].text, c[3].text = label, "(+)", "€", value
    d.add_paragraph("La séance est levée à 18h30.")
    d.add_paragraph("Monsieur Jean Fictif")
    d.add_paragraph("Fait à Woluwé-Saint-Pierre")
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def test_a_real_layout_without_known_client():
    result = from_example.convert(realistic_pv(), None)
    text = from_example.text_of(result.content)
    for leftover in ("TESTFICT", "Essais", "Woluwé", "0987", "deux mille", "23 septembre",
                     "Fictif", " 100", "31/12/2025", "42.310", "2.140", "18h"):  # fmt: skip
        assert leftover not in text, leftover
    assert "présidence de [GÉRANT]" in text and "[ASSOCIÉS]" in text
    assert "S.R.L." not in text  # déjà dans le nom de la société
    holes = from_example.holes_for(result.content, "pv_ag")
    labels = {v["label"] for v in holes.values() if v["field"] == "demander"}
    assert {"Bénéfice d’exploitation", "ATN Auto"} <= labels
    fields = [v["field"] for v in holes.values()]
    assert {"ag.annee", "ag.date", "ag.debut", "ag.fin", "client.ville", "exercice.cloture",
            "client.adresse", "client.localite", "client.representant",
            "client.associes"} <= set(fields)  # fmt: skip


def test_a_template_from_a_filled_document_needs_a_reread_before_activation(client, make_user):
    from django.core.files.uploadedfile import SimpleUploadedFile

    admin = make_user(is_staff=True, capabilities=["clients.edit"])
    client.force_login(admin)
    client.post(reverse("lettre:models"), {"sorte": "pv_ag",
                "modele": SimpleUploadedFile("pv.docx", realistic_pv())})  # fmt: skip
    template = LetterTemplate.objects.get()
    data = {"action": "activer"}
    for key, value in template.holes.items():
        data[f"trou-{key}"], data[f"libelle-{key}"] = value["field"], value["label"]
    url = reverse("lettre:model", args=[template.pk])
    client.post(url, data)
    template.refresh_from_db()
    assert not template.active  # pas relu
    client.post(url, {**data, "relu": "1"})
    template.refresh_from_db()
    assert template.active


def test_names_without_civility_partners_list_and_court():
    d = Word()
    for line in ("Société Essai SRL", "R.P.M. Liège, division Namur — BE 0987.654.394",
                 "La séance est ouverte sous la présidence de Paul Essaiun.",
                 "Sont présents : 1. Paul Essaiun — 120 parts ; 2. Julie Essaideux — 80 parts.",
                 "Décharge est donnée à Paul Essaiun, gérant.",
                 "Paul Essaiun, gérant      Julie Essaideux, associée"):  # fmt: skip
        d.add_paragraph(line)
    out = io.BytesIO()
    d.save(out)
    result = from_example.convert(out.getvalue(), None)
    text = from_example.text_of(result.content)
    assert "Essai" not in text and "Liège" not in text and "120" not in text
    assert "R.P.M. [TRIBUNAL]" in text and "Sont présents : [ASSOCIÉS]." in text
    assert "donnée à [GÉRANT], gérant" in text and "[GÉRANT], gérant      [ASSOCIÉ]" in text
    holes = from_example.holes_for(result.content, "pv_ag")
    assert {"client.associes", "client.representant"} <= {v["field"] for v in holes.values()}


def test_all_leaders_are_written():
    from apps.clients.models import Relation
    from apps.core.testing.factories import ClientFactory, PersonFactory
    from apps.documents import letter

    company = ClientFactory(name="Essai", legal_form="SRL")
    for first, last in (("Paul", "Essaiun"), ("Marie", "Essaideux")):
        Relation.objects.create(entity=company, role=Relation.Role.MANAGER,
                                person=PersonFactory(name=last, first_name=first))  # fmt: skip
    assert letter.FIELDS["client.dirigeants"][1](company) == "Marie Essaideux et Paul Essaiun"


def test_the_typography_of_the_document_is_kept():
    from docx.shared import Pt, RGBColor

    d = Word()
    run = d.add_paragraph().add_run("Société Essai SRL, séance ouverte à 18h00")
    run.font.name, run.font.size, run.bold = "Garamond", Pt(13), True
    run.font.color.rgb = RGBColor(0x1F, 0x4E, 0x79)
    out = io.BytesIO()
    d.save(out)
    result = from_example.convert(out.getvalue(), None)
    kept = letter._open(result.content).paragraphs[0].runs[0]
    assert "[HEURE]" in kept.text
    assert (kept.font.name, kept.font.size, kept.bold) == ("Garamond", Pt(13), True)
    assert kept.font.color.rgb == RGBColor(0x1F, 0x4E, 0x79)


def test_the_server_has_lookalikes_of_the_usual_word_fonts():
    from pathlib import Path

    from django.conf import settings

    root = Path(settings.BASE_DIR)
    rules = (root / "deploy/fonts/60-polices-cabinet.conf").read_text()
    for font in ("Garamond", "Century Gothic", "Aptos", "Book Antiqua"):
        assert f"<family>{font}</family>" in rules
    assert "60-polices-cabinet.conf" in (root / "Dockerfile").read_text()


def test_fonts_the_pdf_cannot_copy_are_reported(monkeypatch):
    from docx.oxml import parse_xml

    d = Word()
    for font in ("Garamond", "Calibri", "Police Maison"):
        d.add_paragraph().add_run(f"Texte en {font}").font.name = font
    out = io.BytesIO()
    d.save(out)
    monkeypatch.setattr(letter, "_installed_fonts", lambda: {"police maison"})
    # Word écrit chaque police utilisée dans word/fontTable.xml ; on l'imite.
    import zipfile

    source = zipfile.ZipFile(io.BytesIO(out.getvalue()))
    rebuilt = io.BytesIO()
    with zipfile.ZipFile(rebuilt, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "word/fontTable.xml":
                ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
                fonts = "".join(f'<w:font w:name="{f}"/>' for f in ("Garamond", "Calibri",
                                                                  "Police Maison"))  # fmt: skip
                fonts += '<w:font w:name="Lato"><w:embedRegular r:id="x"/></w:font>'
                rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
                data = f'<w:fonts xmlns:w="{ns}" xmlns:r="{rel}">{fonts}</w:fonts>'.encode()
                parse_xml(data)
            target.writestr(item, data)
    assert letter.missing_fonts(rebuilt.getvalue()) == ["Garamond"]


def test_another_company_such_as_the_cabinet_is_not_the_client():
    d = Word()
    for line in ("Agence Essai SRL", "Rue des Essais 11", "La séance de Agence Essai est ouverte.",
                 "Mandat donné à la Fiduciaire Exemple & Partenaire Essai SRL."):  # fmt: skip
        d.add_paragraph(line)
    out = io.BytesIO()
    d.save(out)
    text = from_example.text_of(from_example.convert(out.getvalue(), None).content)
    assert text.startswith("[SOCIÉTÉ]") and "La séance de [SOCIÉTÉ] est" in text
    assert "Fiduciaire Exemple & Partenaire Essai SRL" in text


def placeholder_model() -> bytes:
    """Un modèle vide d'un autre cabinet : ses propres repères entre crochets et des « XXX »."""
    d = Word()
    for line in ("[DENOMINATION SOCIALE]", "au capital de [MONTANT DU CAPITAL SOCIAL] euros",
                 "R.C.S. [GTC COMPETENT]", "L'an deux-mille-vingt-trois,",
                 "réunis [LIEU DE REUNION], convocation par le [NOM ET PRENOM DU DIRIGEANT]",
                 "Sont présents :", "XXX, titulaire de XXX droits sociaux",
                 "présidée par Monsieur [NOM DU DIRIGEANT], en sa qualité de [GERANT / PRESIDENT]",
                 "possèdent [XXX] droits sociaux", "décide de [OBJET DE LA MODIFICATION]",
                 "Ordre du jour : [OBJET DE LA MODIFICATION]", "M. XXX"):  # fmt: skip
        d.add_paragraph(line)
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def test_the_placeholders_of_another_model_are_left_alone_and_well_named():
    result = from_example.convert(placeholder_model(), None)
    text = from_example.text_of(result.content)
    assert "[GÉRANT]" not in text and "[[" not in text  # rien remplacé dans les repères
    assert "XXX, titulaire de XXX" in text and "M. XXX" in text and "[ANNÉE]" in text
    holes = from_example.holes_for(result.content, "pv_ag")
    asked = {v["label"] for v in holes.values() if v["field"] == letter.ASK}
    assert {"Montant du capital social", "Greffe / tribunal compétent", "Lieu de reunion",
            "Gerant / president", "Objet de la modification", "Nom"} <= asked  # fmt: skip
    fields = [v["field"] for v in holes.values()]
    assert "client.siege" not in fields  # le greffe n'est pas une adresse
    assert fields.count("client.representant") == 2  # les deux « dirigeant »


def test_the_same_placeholder_is_asked_once(client, make_user):
    from django.core.files.uploadedfile import SimpleUploadedFile

    admin = make_user(is_staff=True, capabilities=["clients.edit"])
    client.force_login(admin)
    upload = SimpleUploadedFile("pv.docx", placeholder_model())
    client.post(reverse("lettre:models"), {"sorte": "pv_ag", "modele": upload})
    template = LetterTemplate.objects.get()
    labels = [label for _, label in letter.questions(template)]
    assert labels.count("Objet de la modification") == 1
    key = next(k for k, label in letter.questions(template) if label == "Objet de la modification")
    company = ClientFactory(name="Essai", legal_form="SRL")
    filled = letter.fill(template, company, {key: "transférer le siège"}, {})
    text = "\n".join(p.text for p in Word(io.BytesIO(filled)).paragraphs)
    assert text.count("transférer le siège") == 2
