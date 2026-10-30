"""Checklists IPP de départ (D-118), définies avec Jeremy le 30/10/2026. Modifiables ensuite
dans Paramètres › Checklists de clôture."""

from django.db import migrations

VAT = [
    ("Achats", "Toutes les factures d'achat de l'année encodées"),
    ("Ventes / recettes", "Toutes les ventes ou recettes de l'année encodées"),
    ("Banque / Financier", "Comptes en banque et cartes (Visa, Master) jusqu'au 31/12"),
    ("Caisse", "Solde justifié, jamais négatif"),
    ("Amortissements", "Amortissements de l'année comptabilisés"),
    ("Emprunts", "Intérêts et capital séparés"),
    ("Comptes TVA", "Comptes TVA soldés et concordants avec les déclarations"),
    ("Fournisseurs ouverts", "Fournisseurs encore ouverts vérifiés"),
    ("Clients ouverts", "Clients encore ouverts vérifiés"),
    ("Notes de frais", "Notes de frais encodées et justifiées"),
]
NO_VAT = [item for item in VAT if item[0] not in ("Comptes TVA", "Clients ouverts")]
MANAGER = [
    ("Frais réels ou forfait", "Le plus avantageux retenu"),
    ("Voiture", "Frais de voiture et part déductible"),
    ("Restaurants et cadeaux", "Part non déductible retirée"),
    ("Déduction pour investissement", "Investissements de l'année qui y donnent droit"),
    ("Versements anticipés", "Versements de l'année repris"),
    ("Conjoint aidant / quotient conjugal", "Répartition vérifiée"),
]


def seed(apps, schema_editor):
    CommonItem = apps.get_model("closing", "CommonItem")
    for kind, items in (("ipp_tva", VAT), ("ipp_sans_tva", NO_VAT), ("ipp_gestion", MANAGER)):
        if CommonItem.objects.filter(kind=kind).exists():
            continue
        for position, (label, hint) in enumerate(items, start=1):
            CommonItem.objects.create(kind=kind, label=label, hint=hint, position=position)


class Migration(migrations.Migration):
    dependencies = [("closing", "0008_cloture_ipp")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
