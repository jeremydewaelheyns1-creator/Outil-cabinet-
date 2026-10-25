"""Pièces d'identité : lignes « machine », vérifications, application automatique (D-035).

Toutes les cartes sont fictives (lignes fabriquées par `mrz.build_td1`) ; l'exemple officiel
de l'OACI sert à vérifier le calcul des chiffres de contrôle.
"""

from datetime import date, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import ContactPoint, Relation
from apps.core.models import AccessLog
from apps.core.testing.factories import ClientFactory, PersonFactory
from apps.core.testing.numbers import national_number
from apps.documents import identity, mrz, services
from apps.documents.models import Document, DocumentRequest, IdentityCard

pytestmark = pytest.mark.django_db

ICAO_EXAMPLE = (
    "I<UTOD231458907<<<<<<<<<<<<<<<\n7408122F1204159UTO<<<<<<<<<<<6\nERIKSSON<<ANNA<MARIA<<<<<<<<<<"
)


def future(years: int = 5) -> date:
    return timezone.localdate() + timedelta(days=365 * years)


def card_text(person, *, expiry: date | None = None, nn: str | None = None, number="592123456789"):
    expiry = expiry or future()
    birth = person.birth_date or date(1985, 7, 30)
    lines = mrz.build_td1(
        document_number=number,
        surname=person.name,
        given_names=person.first_name,
        birth=birth.strftime("%y%m%d"),
        expiry=expiry.strftime("%y%m%d"),
        national_number=nn if nn is not None else (person.national_number or ""),
    )
    return "SPECIMEN\n" + "\n".join(lines)


@pytest.fixture
def reader(monkeypatch):
    """Remplace la lecture (OCR) par un texte fourni par le test. Les traitements prévus
    « après la transaction » (événements) s'exécutent aussitôt, comme en production."""
    from django.db import transaction

    box = {"text": None}
    monkeypatch.setattr(identity, "READER", lambda document: box["text"])
    monkeypatch.setattr(transaction, "on_commit", lambda func, *a, **k: func())
    return box


def setup_company():
    company = ClientFactory()
    ContactPoint.objects.create(client=company, kind="email", value="compta@fictif.test")
    person = PersonFactory(
        name="Fictif", first_name="Anne", national_number=national_number(7, "850730"),
        birth_date=date(1985, 7, 30),
    )  # fmt: skip
    Relation.objects.create(entity=company, person=person, role="manager")
    return company, person


def upload_card(company, person):
    image = SimpleUploadedFile("carte.png", b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    return services.store(company, image, title="Carte", case="pieces-identite", person=person)


# --- Lignes « machine » ----------------------------------------------------------------------


def test_icao_official_example_is_valid():
    result = mrz.read(ICAO_EXAMPLE)
    assert result is not None and result.valid
    assert (result.surname, result.given_names) == ("ERIKSSON", "ANNA MARIA")
    assert result.document_number == "D23145890"
    assert result.birth_date == date(1974, 8, 12)


def test_belgian_long_card_number_and_national_number():
    lines = mrz.build_td1(
        document_number="592123456789", surname="FICTIF", given_names="ANNE",
        birth="850730", expiry="310412", national_number="85073000160",
    )  # fmt: skip
    result = mrz.read("\n".join(lines))
    assert result.valid and result.document_number == "592123456789"
    assert result.national_number == "85073000160"
    assert "85073000160" not in repr(result)  # jamais dans une trace


def test_a_single_misread_character_is_caught():
    lines = mrz.build_td1(
        document_number="592123456789", surname="FICTIF", given_names="ANNE",
        birth="850730", expiry="310412",
    )  # fmt: skip
    lines[1] = lines[1][:9] + ("8" if lines[1][9] != "8" else "9") + lines[1][10:]
    result = mrz.read("\n".join(lines))
    assert not result.valid and "date d'expiration" in result.failed_checks


# --- Application automatique (tout est vert) -------------------------------------------------


def test_valid_card_is_applied_without_confirmation(reader):
    company, person = setup_company()
    reader["text"] = card_text(person, expiry=date(2031, 4, 12))
    document = upload_card(company, person)
    card = IdentityCard.objects.get()
    document.refresh_from_db()
    assert card.valid_until == date(2031, 4, 12) and card.auto_applied
    assert card.card_number == "592123456789" and card.masked_number == "•••• 6789"
    assert document.auto_filed and not document.review_needed


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("unreadable", "illisibles"),
        ("wrong_name", "nom lu"),
        ("wrong_nn", "numéro national"),
        ("expired", "expirée"),
        ("bad_digit", "Contrôle de lecture"),
    ],
)
def test_any_doubt_means_to_confirm(reader, change, reason):
    company, person = setup_company()
    text = card_text(person)
    if change == "unreadable":
        text = "photo floue"
    elif change == "wrong_name":
        other = PersonFactory(name="Autre", first_name="Paul", birth_date=person.birth_date,
                              national_number=None)  # fmt: skip
        text = card_text(other, nn=person.national_number)
    elif change == "wrong_nn":
        text = card_text(person, nn=national_number(8, "850730"))
    elif change == "expired":
        text = card_text(person, expiry=timezone.localdate() - timedelta(days=3))
    elif change == "bad_digit":
        lines = text.splitlines()
        lines[2] = lines[2][:2] + ("1" if lines[2][2] != "1" else "2") + lines[2][3:]
        text = "\n".join(lines)
    reader["text"] = text
    document = upload_card(company, person)
    document.refresh_from_db()
    assert not IdentityCard.objects.exists()
    assert document.review_needed and reason in document.review_reason
    assert person.national_number not in document.review_reason


def test_person_without_national_number_is_checked_on_birth_date(reader):
    company, person = setup_company()
    person.national_number = None
    person.save()
    reader["text"] = card_text(person, nn="")
    upload_card(company, person)
    assert IdentityCard.objects.get().auto_applied


def test_undo_puts_the_card_back_to_confirm(reader, web):
    company, person = setup_company()
    reader["text"] = card_text(person)
    document = upload_card(company, person)
    card = IdentityCard.objects.get()
    response = web.post(reverse("clients:identity_undo", args=[company.pk, card.pk]))
    assert response.status_code == 302
    document.refresh_from_db()
    assert not IdentityCard.objects.exists() and document.review_needed
    assert AccessLog.objects.filter(action="delete").exists()


def test_undo_is_limited_in_time(reader):
    company, person = setup_company()
    reader["text"] = card_text(person)
    upload_card(company, person)
    card = IdentityCard.objects.get()
    IdentityCard.objects.filter(pk=card.pk).update(created_at=timezone.now() - timedelta(days=8))
    card.refresh_from_db()
    assert not identity.can_undo(card)


def test_manual_confirmation(reader, web):
    company, person = setup_company()
    reader["text"] = None
    document = upload_card(company, person)
    url = reverse("clients:identity_confirm", args=[company.pk, document.pk])
    web.post(url, {"valid_until": "2032-01-31", "card_number": "592000000011"})
    card = IdentityCard.objects.get()
    assert card.source == "manual" and card.valid_until == date(2032, 1, 31)
    document.refresh_from_db()
    assert not document.review_needed


def test_received_request_goes_through_the_same_checks(reader, web):
    company, person = setup_company()
    request = services.create_request(company, "identity_card", person=person)
    reader["text"] = card_text(person)
    image = SimpleUploadedFile("carte.jpg", b"\xff\xd8\xff" + b"0" * 20)
    web.post(reverse("clients:request_receive", args=[company.pk, request.pk]), {"file": image})
    assert IdentityCard.objects.get().auto_applied
    request.refresh_from_db()
    assert request.status == DocumentRequest.Status.RECEIVED


# --- Situation et relances ----------------------------------------------------------------


def test_case_colours(reader, web):
    company, person = setup_company()
    url = reverse("clients:documents", args=[company.pk])
    assert "carte(s) manquante(s)" in web.get(url).content.decode()  # rouge
    reader["text"] = None
    upload_card(company, person)
    assert "à confirmer" in web.get(url).content.decode()  # orange
    Document.objects.update(review_needed=False)
    soon = timezone.localdate() + timedelta(days=10)
    IdentityCard.objects.create(person=person, valid_until=soon, source="manual")
    assert "expirent bientôt" in web.get(url).content.decode()  # orange
    IdentityCard.objects.create(person=person, valid_until=future(), source="manual")
    html = web.get(url).content.decode()
    assert "Toutes les cartes sont valables" in html  # vert


def test_renewal_is_requested_once_before_expiry(settings):
    settings.IDENTITY_RENEWAL_DAYS = 30
    company, person = setup_company()
    IdentityCard.objects.create(
        person=person, valid_until=timezone.localdate() + timedelta(days=25), source="manual"
    )
    assert identity.request_renewals() == 1
    assert identity.request_renewals() == 0  # une seule demande en cours
    request = DocumentRequest.objects.get()
    assert request.person == person and request.client == company
    assert request.title == "Carte d'identité de Fictif Anne"


def test_no_renewal_when_far_from_expiry(settings):
    _company, person = setup_company()
    IdentityCard.objects.create(person=person, valid_until=future(), source="manual")
    assert identity.request_renewals() == 0


def test_identity_page_never_shows_the_national_number(reader, web):
    company, person = setup_company()
    reader["text"] = card_text(person)
    upload_card(company, person)
    html = web.get(reverse("clients:document_case", args=[company.pk, "pieces-identite"]))
    text = html.content.decode()
    assert person.national_number not in text and "592123456789" not in text


@pytest.mark.skipif(not __import__("shutil").which("tesseract"), reason="Tesseract absent")
def test_real_ocr_on_a_fictive_specimen(settings, monkeypatch):
    """De bout en bout : image fictive → OCR local → contrôles → carte enregistrée."""
    from pathlib import Path

    from django.db import transaction

    settings.IDENTITY_OCR_ENABLED = True
    monkeypatch.setattr(identity, "READER", identity.ocr_text)
    monkeypatch.setattr(transaction, "on_commit", lambda func, *a, **k: func())
    company = ClientFactory()
    person = PersonFactory(
        name="Fictif", first_name="Anne", national_number=national_number(7, "850730"),
        birth_date=date(1985, 7, 30),
    )  # fmt: skip
    Relation.objects.create(entity=company, person=person, role="manager")
    content = (Path(__file__).parent / "fixtures" / "carte_fictive_dos.png").read_bytes()
    services.store(
        company, SimpleUploadedFile("dos.png", content), title="Carte",
        case="pieces-identite", person=person,
    )  # fmt: skip
    card = IdentityCard.objects.get()
    assert card.auto_applied and card.valid_until == date(2031, 4, 12)


def test_shifted_national_number_is_caught():
    """Une lettre parasite décale le numéro national : son propre contrôle (modulo 97) le voit,
    même si le contrôle global tombe juste par hasard (cas réel trouvé sur une photo fictive)."""
    lines = [
        "IDBEL592754212<1190<<<<<<<<<<<",
        "5412116F2904021BEFL54121145941",
        "EXEMPLE<<MARC<<<<<<<<<<<<<<<<<",
    ]
    result = mrz.parse_td1(lines)
    assert not result.valid and "numéro national" in result.failed_checks


def test_one_misread_letter_in_the_name_is_tolerated_only_with_the_same_national_number():
    person = PersonFactory(name="Lambert", first_name="Lucie", national_number=national_number(4))
    good = mrz.read(card_text(person))
    assert good is not None
    good.surname = "YLAMBERT"  # une lettre parasite lue devant le nom
    assert identity.problems(good, person, timezone.localdate()) == []
    good.national_number = national_number(5)
    assert "Le nom lu ne correspond pas à la fiche" in identity.problems(
        good, person, timezone.localdate()
    )


@pytest.mark.skipif(not __import__("shutil").which("tesseract"), reason="Tesseract absent")
def test_reads_a_phone_photo_taken_at_an_angle(settings):
    """Photo de téléphone FICTIVE : carte de travers, floue, posée sur une table, enregistrée
    « couchée » avec l'orientation dans les métadonnées (comme un iPhone)."""
    from pathlib import Path

    settings.IDENTITY_OCR_ENABLED = True
    content = (
        Path(__file__).parent / "fixtures" / "photo_telephone_carte_fictive.jpg"
    ).read_bytes()
    result = mrz.read(identity.ocr_bytes(content, "image/jpeg") or "")
    assert result is not None and result.valid
    assert result.document_number == "592669927874" and result.expiry_date == date(2029, 9, 6)


def test_a_stuck_reading_does_not_block(monkeypatch):
    import subprocess

    from apps.documents import card_reader

    def too_long(*args, **kwargs):
        raise subprocess.TimeoutExpired("tesseract", 1)

    monkeypatch.setattr(subprocess, "run", too_long)
    assert card_reader.tesseract(__import__("numpy").zeros((10, 10), dtype="uint8")) == ""
