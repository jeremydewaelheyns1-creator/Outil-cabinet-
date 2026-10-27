"""Fiches fictives complètes : tout ce qu'une identification exige (D-085)."""

from datetime import date, timedelta

from django.utils import timezone

from apps.clients.models import Client
from apps.core.testing.numbers import enterprise_number, national_number
from apps.documents.models import IdentityCard, RiskAssessment

_seed = [9000]


def complete(client: Client) -> Client:
    _seed[0] += 1
    if client.is_person:
        client.birth_date = client.birth_date or date(1980, 1, 1)
        client.nationality = client.nationality or "BE"
        client.national_number = client.national_number or national_number(_seed[0], "800101")
        IdentityCard.objects.create(person=client, valid_until=timezone.localdate()
                                    + timedelta(days=900), source="manual")  # fmt: skip
    else:
        client.legal_form = client.legal_form or "SRL"
        client.enterprise_number = client.enterprise_number or enterprise_number(_seed[0])
    client.street = client.street or "Rue Fictive"
    client.house_number = client.house_number or "1"
    client.postal_code = client.postal_code or "5000"
    client.city = client.city or "Namur"
    client.save()
    if not RiskAssessment.objects.filter(client=client).exists():
        review = timezone.localdate() + timedelta(days=1000)
        RiskAssessment.objects.create(
            client=client, answers={}, score=0, level="low", next_review=review
        )
    return client
