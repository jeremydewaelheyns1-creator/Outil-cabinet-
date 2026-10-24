"""Remplit une base de démonstration avec des données entièrement fictives.

    python manage.py demo

Réservé au poste de développement et à l'environnement d'essai : la commande refuse de
s'exécuter si la base contient déjà des clients (pour ne jamais se mélanger à de vraies
données), sauf avec --vider, qui n'est accepté qu'en mode DEBUG.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.clients.models import Assignment, Client, ContactPoint, Relation
from apps.core.models import Portfolio, SecurityProfile, User
from apps.core.testing.numbers import enterprise_number, national_number

COMPANIES = [
    ("Boulangerie du Moulin Fictif", "SRL", "Namur", "5000", "Rue de l'Ange", "12"),
    ("Garage des Trois Ponts Fictif", "SRL", "Dinant", "5500", "Rue Grande", "45"),
    ("Holding Familiale Fictive", "SA", "Namur", "5000", "Boulevard du Nord", "8"),
    ("Cabinet Médical Imaginaire", "SRL", "Gembloux", "5030", "Avenue de la Faculté", "3"),
    ("Les Amis du Patrimoine Fictif", "ASBL", "Andenne", "5300", "Place des Tilleuls", "1"),
    ("Menuiserie Invention", "SC", "Ciney", "5590", "Chaussée de Namur", "120"),
    ("Brasserie de l'Exemple", "SRL", "Namur", "5000", "Rue de Fer", "33"),
    ("Transports Démo & Fils", "SA", "Jambes", "5100", "Avenue Prince de Liège", "77"),
]
PERSONS = [
    ("Lambert", "Sophie", "Namur"),
    ("Dubois", "Marc", "Dinant"),
    ("Lambert", "Thomas", "Namur"),
    ("Renard", "Claire", "Gembloux"),
    ("Simon", "Julien", "Andenne"),
    ("Lemaire", "Nathalie", "Ciney"),
]


class Command(BaseCommand):
    help = "Crée des données de démonstration fictives (clients, relations, utilisateur)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--vider", action="store_true", help="Supprime d'abord les clients (DEBUG seulement)."
        )
        parser.add_argument("--email", default="demo@cabinet.test")
        parser.add_argument("--mot-de-passe", default="demonstration-2026")

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        if options["vider"]:
            if not settings.DEBUG:
                raise CommandError("--vider n'est permis qu'en développement (DEBUG).")
            from apps.documents.models import Document, DocumentRequest, IdentityCard

            IdentityCard.objects.all().delete()
            Document.objects.all().delete()
            DocumentRequest.objects.all().delete()
            Relation.objects.all().delete()
            Client.objects.all().delete()
        elif Client.objects.exists():
            raise CommandError("La base contient déjà des clients : démonstration refusée.")

        cabinet = Portfolio.objects.get_or_create(name="Cabinet")[0]
        dinant = Portfolio.objects.get_or_create(name="Bureau de Dinant")[0]
        profile = SecurityProfile.objects.get(name="Responsable")
        user, created = User.objects.get_or_create(
            email=options["email"],
            defaults={
                "first_name": "Camille",
                "last_name": "Démo",
                "initials": "CD",
                "profile": profile,
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            user.set_password(options["mot_de_passe"])
            user.save()

        companies = []
        for index, (name, form, city, postal, street, number) in enumerate(COMPANIES):
            kind = Client.Kind.NONPROFIT if form == "ASBL" else Client.Kind.COMPANY
            client = Client.objects.create(
                kind=kind,
                name=name,
                legal_form=form,
                enterprise_number=enterprise_number(500 + index),
                reference=f"D{index + 1:03d}",
                portfolio=dinant if city == "Dinant" else cabinet,
                street=street,
                house_number=number,
                postal_code=postal,
                city=city,
                vat_status=Client.VatStatus.SUBJECT if kind == Client.Kind.COMPANY else "",
                vat_periodicity=Client.VatPeriodicity.QUARTERLY if index % 2 else "monthly",
                fiscal_year_end_month=12,
                fiscal_year_end_day=31,
                client_since=date(2015 + index, 1, 1),
            )
            ContactPoint.objects.create(
                client=client, kind="email", value=f"compta{index}@exemple.test", is_primary=True
            )
            Assignment.objects.create(client=client, user=user, role=Assignment.Role.MANAGER)
            companies.append(client)

        persons = []
        for index, (name, first_name, city) in enumerate(PERSONS):
            persons.append(
                Client.objects.create(
                    kind=Client.Kind.PERSON,
                    name=name,
                    first_name=first_name,
                    national_number=national_number(index + 1, birth=f"7{index}0315"),
                    birth_date=date(1970 + index, 3, 15),
                    portfolio=cabinet,
                    city=city,
                    reference=f"P{index + 1:03d}",
                )
            )

        bakery, garage, holding, medical, asbl, joinery, brewery, transport = companies
        sophie, marc, thomas, claire, julien, nathalie = persons
        shareholder = Relation.Role.SHAREHOLDER
        relations = [
            (holding, sophie, shareholder, "70"),
            (holding, thomas, shareholder, "30"),
            (bakery, holding, shareholder, "80"),
            (bakery, marc, shareholder, "20"),
            (bakery, sophie, Relation.Role.MANAGER, None),
            (garage, marc, shareholder, "100"),
            (garage, marc, Relation.Role.MANAGER, None),
            (medical, claire, shareholder, "50"),
            (medical, julien, shareholder, "50"),
            (medical, claire, Relation.Role.BENEFICIAL_OWNER, None),
            (asbl, julien, Relation.Role.DIRECTOR, None),
            (asbl, nathalie, Relation.Role.DIRECTOR, None),
            (joinery, nathalie, shareholder, "20"),
            (joinery, thomas, Relation.Role.MANAGING_DIRECTOR, None),
            (brewery, holding, shareholder, "40"),
            (brewery, claire, shareholder, "60"),
            (transport, marc, Relation.Role.DIRECTOR, None),
            (sophie, thomas, Relation.Role.SPOUSE, None),
        ]
        for entity, person, role, share in relations:
            Relation.objects.create(
                entity=entity,
                person=person,
                role=role,
                share_percentage=Decimal(share) if share else None,
                start_date=date(2018, 1, 1),
            )
        self._official_snapshots(companies, persons)
        self._documents(companies, persons, user)
        from apps.tasks.generator import generate_all

        run = generate_all()
        self._vat(companies, user)
        self._compliance(companies, user)
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(companies) + len(persons)} fiches fictives, {run.created} échéances. "
                f"Connexion : {user.email}"
            )
        )

    @staticmethod
    def _vat(companies: list[Client], user: User) -> None:
        """Grille TVA fictive (D-040) : trimestres passés terminés, T3 importé depuis Intervat."""
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.vat import importer
        from apps.vat import services as vat
        from apps.vat.models import Column, Status

        company = next(
            c for c in companies
            if c.vat_status == Client.VatStatus.SUBJECT and c.vat_periodicity == "quarterly"
        )  # fmt: skip
        amounts = {(2025, 4): "3177.78", (2026, 1): "2957.28", (2026, 2): "2292.13"}
        for (year, quarter), amount in amounts.items():
            filing = vat.filing_for(company, vat.period(year, quarter=quarter))
            filing.grid_71 = Decimal(amount)
            filing.advance_1 = filing.advance_2 = Decimal("1000.00")
            filing.save()
            for column in (Column.DOCS, Column.DONE, Column.FILED, Column.CLIENT):
                vat.set_status(filing, column, Status.DONE, user=user,
                               on=filing.period_end + timedelta(days=15))  # fmt: skip
            vat.set_status(filing, Column.IC, Status.NOT_NEEDED, user=user)
        company.contact_title, company.contact_name = Client.Title.MR, "Dubois"
        company.save(update_fields=["contact_title", "contact_name"])
        number = company.enterprise_number or ""
        xml = (
            '<?xml version="1.0"?><ns2:VATConsignment '
            'xmlns="http://www.minfin.fgov.be/InputCommon" '
            'xmlns:ns2="http://www.minfin.fgov.be/VATConsignment"><ns2:VATDeclaration>'
            f"<ns2:Declarant><VATNumber>{number}</VATNumber></ns2:Declarant>"
            "<ns2:Period><ns2:Quarter>3</ns2:Quarter><ns2:Year>2026</ns2:Year></ns2:Period>"
            '<ns2:Data><ns2:Amount GridNumber="71">4272.44</ns2:Amount></ns2:Data>'
            "</ns2:VATDeclaration></ns2:VATConsignment>"
        ).encode()
        files = [
            SimpleUploadedFile("declaration-t3.xml", xml),
            SimpleUploadedFile(
                "declaration-t3.pdf", demo_pdf(f"Declaration TVA BE{number} T3 2026")
            ),
        ]
        importer.import_files(files, clients=Client.objects.filter(pk=company.pk), user=user)
        t3 = vat.filing_for(company, vat.period(2026, quarter=3))
        t3.advance_1 = t3.advance_2 = Decimal("2100.00")
        t3.remark = "Régularisation faite"
        # Données de paiement visiblement fictives (comme si elles avaient été lues sur le PDF).
        t3.payment_iban = "BE00 0000 0000 0000"
        t3.payment_reference = "+++000/0000/00097+++"
        t3.save()
        for column in (Column.DOCS, Column.DONE):
            vat.set_status(t3, column, Status.DONE, user=user)
        vat.set_status(t3, Column.IC, Status.NOT_NEEDED, user=user)
        t4 = vat.filing_for(company, vat.period(2026, quarter=4))
        vat.set_status(
            t4, Column.DOCS, Status.IN_PROGRESS, user=user, comment="Ventes d'octobre reçues"
        )

    @staticmethod
    def _official_snapshots(companies: list[Client], persons: list[Client]) -> None:
        """Relevés fictifs des sites officiels (aucune consultation réelle en démo)."""
        from datetime import timedelta

        from apps.integrations.models import OfficialSnapshot

        today = date.today()
        bakery = companies[0]
        sophie, marc = persons[0], persons[1]
        names = {bakery.pk: [("Gérant", sophie), ("Gérant", marc)]}
        for index, company in enumerate(companies):
            functions = [
                {"role": role, "name": p.name, "first_name": p.first_name,
                 "enterprise_number": "", "since": "2018-01-01"}
                for role, p in names.get(company.pk, [])
            ]  # fmt: skip
            for relation in company.relations_as_entity.filter(
                role__in=Relation.MANAGEMENT_ROLES
            ).select_related("person"):
                if relation.person.pk not in {p.pk for _, p in names.get(company.pk, [])}:
                    functions.append(
                        {"role": relation.get_role_display(), "name": relation.person.name,
                         "first_name": relation.person.first_name, "enterprise_number": "",
                         "since": "2018-01-01"}
                    )  # fmt: skip
            recent = (today - timedelta(days=12)).isoformat()
            publications = [
                {"published_on": "2022-06-20", "number": f"00{index}5678",
                 "subject": "SIEGE SOCIAL - TRANSFERT", "tags": ["Siège"], "pdf_url": ""},
                {"published_on": "2018-01-15", "number": f"00{index}1234",
                 "subject": "RUBRIQUE CONSTITUTION (NOUVELLE PERSONNE MORALE)",
                 "tags": ["Constitution"], "pdf_url": ""},
            ]  # fmt: skip
            if company is bakery:
                publications.insert(
                    0,
                    {"published_on": recent, "number": "0099999",
                     "subject": "DEMISSIONS, NOMINATIONS", "tags": ["Démission", "Nomination"],
                     "pdf_url": ""},
                )  # fmt: skip
            filings = [
                {"reference": f"{year + 1}-0000{index}{year % 10}",
                 "deposit_date": f"{year + 1}-07-2{index % 9}",
                 "exercise_start": f"{year}-01-01", "exercise_end": f"{year}-12-31",
                 "model": "Micro (m01-f)", "deposit_type": "Initial",
                 "general_assembly": f"{year + 1}-06-1{index % 9}"}
                for year in (2025, 2024, 2023)
            ]  # fmt: skip
            for source, items in (
                (OfficialSnapshot.Source.KBO, functions),
                (OfficialSnapshot.Source.MONITEUR, publications),
                (OfficialSnapshot.Source.NBB, filings),
            ):
                OfficialSnapshot.objects.create(
                    client=company, source=source, status=OfficialSnapshot.Status.OK, items=items
                )

    @staticmethod
    def _compliance(companies: list[Client], user: User) -> None:
        """Paperasse anti-blanchiment (D-048 à D-052) : fiche guidée, demande groupée, résumé."""
        from django.utils import timezone

        from apps.documents import compliance, digest, generation, risk

        brewery, medical = companies[6], companies[3]
        risk.save(
            brewery,
            {"sensitive_sector": True, "cash": True, "new_client": False},
            user=user,
            comment="Débit de boissons : paiements en espèces fréquents (exemple fictif).",
        )
        generation.generate(medical, "lettre_mission", user=user)
        compliance.ask_everything(medical, user)
        digest.monthly(timezone.localdate().replace(day=1))

    @staticmethod
    def _documents(companies: list[Client], persons: list[Client], user: User) -> None:
        """Documents et demandes fictifs (petits PDF générés, aucun contenu réel)."""
        from datetime import timedelta

        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.utils import timezone

        from apps.documents import services
        from apps.documents.models import DocumentRequest

        def fake_pdf(label: str) -> SimpleUploadedFile:
            return SimpleUploadedFile("demo.pdf", demo_pdf(label), content_type="application/pdf")

        bakery, garage = companies[0], companies[1]
        sophie, marc = persons[0], persons[1]
        services.store(
            bakery, fake_pdf("lettre de mission"), title="Lettre de mission signée (2024)",
            case="lettre-de-mission", doc_type="lettre_mission", user=user,
        )  # fmt: skip
        today0 = timezone.localdate()
        aml = [
            ("identification_client", "Identification du client", None, None),
            ("identification_mandataire", "Identification du mandataire", sophie, None),
            ("fiche_risque", "Fiche de détermination du niveau de risque", None,
             today0 + timedelta(days=44)),
        ]  # fmt: skip
        from apps.documents import types as doc_types

        for doc_type, title, who, expires in aml:
            services.store(
                bakery, fake_pdf(title), title=title, case=doc_types.BY_SLUG[doc_type].case,
                doc_type=doc_type, person=who, expires_on=expires, user=user,
            )  # fmt: skip
        services.store(
            bakery, fake_pdf("declaration UBO"), title="Déclaration des bénéficiaires effectifs",
            case="declaration-ubo", doc_type="declaration_ubo", user=user,
        )  # fmt: skip
        services.store(
            bakery, fake_pdf("extrait registre UBO"), title="Extrait du registre UBO",
            case="ubo", doc_type="extrait_ubo", user=user,
        )  # fmt: skip
        services.store(
            garage, fake_pdf("fiche de risque"), title="Fiche de détermination du niveau de risque",
            case="fiche-risque", doc_type="fiche_risque",
            expires_on=today0 - timedelta(days=12), user=user,
        )  # fmt: skip
        services.store(
            bakery, fake_pdf("statuts"), title="Statuts coordonnés", folder="legal", user=user
        )
        services.store(
            bakery, fake_pdf("isoc"), title="Déclaration ISOC exercice 2024", folder="isoc",
            user=user,
        )  # fmt: skip
        card_doc = services.store(
            bakery, fake_pdf("carte"), title="Carte d'identité de Lambert Sophie",
            case="pieces-identite", person=sophie, user=user,
        )  # fmt: skip
        from apps.documents.models import IdentityCard

        today_ = timezone.localdate()
        IdentityCard.objects.create(
            person=sophie, document=card_doc, card_number="592000000017",
            valid_until=today_ + timedelta(days=4 * 365), source="manual", created_by=user,
        )  # fmt: skip
        # Marc : carte qui expire bientôt (orange), nouvelle carte déjà demandée.
        IdentityCard.objects.create(
            person=marc, card_number="592000000025", valid_until=today_ + timedelta(days=10),
            source="manual", created_by=user,
        )  # fmt: skip
        late = services.create_request(garage, "identity_card", person=marc, user=user)
        # Une demande plus ancienne, déjà relancée deux fois sans réponse (case en rouge).
        DocumentRequest.objects.filter(pk=late.pk).update(
            created_at=timezone.now() - timedelta(days=21)
        )
        today = timezone.localdate()
        for _ in range(2):  # les deux rappels sont partis, toujours rien 15 jours après
            DocumentRequest.objects.filter(pk=late.pk).update(next_reminder_on=today)
            services.send_due_reminders(today)
        DocumentRequest.objects.filter(pk=late.pk).update(next_reminder_on=today)
        services.create_request(bakery, "identity_card", person=marc, user=user)


def demo_pdf(title: str) -> bytes:
    """Petit PDF valide d'une page, clairement marqué comme fictif (démonstration)."""
    lines = [
        ("F1", 22, 72, 760, title.upper()),
        ("F2", 12, 72, 730, "DOCUMENT FICTIF - DEMONSTRATION"),
        ("F2", 11, 72, 690, "Ce document a ete genere automatiquement pour la demo de l'outil."),
        ("F2", 11, 72, 672, "Il ne contient aucune donnee reelle."),
    ]
    text = "".join(
        f"BT /{font} {size} Tf {x} {y} Td ({line.replace('(', '').replace(')', '')}) Tj ET\n"
        for font, size, x, y, line in lines
    )
    stream = text.encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)
