"""Remplit une base de démonstration avec des données entièrement fictives.

    python manage.py demo

Réservé au poste de développement et à l'environnement d'essai : la commande refuse de
s'exécuter si la base contient déjà des clients (pour ne jamais se mélanger à de vraies
données), sauf avec --vider, qui n'est accepté qu'en mode DEBUG.
"""

from datetime import date
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
        from apps.tasks.generator import generate_all

        run = generate_all()
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(companies) + len(persons)} fiches fictives, {run.created} échéances. "
                f"Connexion : {user.email}"
            )
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
