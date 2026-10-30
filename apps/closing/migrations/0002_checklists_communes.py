"""Les deux checklists communes de départ, définies par Jeremy le 30/10/2026 (D-111).
Les phrases d'aide sont des propositions, modifiables dans Paramètres."""

from django.db import migrations

COMMON = [
    ("Achats", "Toutes les factures d'achat de l'exercice encodées", "both"),
    ("Ventes", "Toutes les factures de vente de l'exercice encodées", "tva"),
    ("Banque / Financier", "Comptes en banque et cartes Visa / Mastercard encodés jusqu'à la fin de l'exercice, soldes concordants", "both"),
    ("Compte d'attente (499)", "Soldé", "both"),
    ("Salaires (453/454/455)", "Concordent avec le secrétariat social", "both"),
    ("Caisse", "Solde justifié, jamais négatif", "both"),
    ("Transfert interne (580)", "Soldé", "both"),
    ("Amortissements", "Comptabilisés pour l'exercice", "both"),
    ("Reclassement de crédit (17/42)", "Part à un an au plus reclassée", "both"),
    ("Cut-off (490/491/492/493)", "Charges et produits rattachés au bon exercice", "both"),
    ("Factures / NC à recevoir", "Comptabilisées", "tva"),
    ("Fournisseurs ouverts", "Vérifiés", "both"),
    ("Clients ouverts", "Vérifiés", "tva"),
    ("Notes de frais", "Encodées et justifiées", "both"),
    ("Comptes TVA", "Concordent avec les déclarations de l'exercice", "tva"),
    ("Listing clients", "Déposé et concordant", "tva"),
]


def seed(apps, schema_editor):
    CommonItem = apps.get_model("closing", "CommonItem")
    if CommonItem.objects.exists():
        return
    for kind in ("tva", "sans_tva"):
        position = 0
        for label, hint, scope in COMMON:
            if scope == "both" or scope == kind:
                position += 1
                CommonItem.objects.create(kind=kind, label=label, hint=hint, position=position)


class Migration(migrations.Migration):
    dependencies = [("closing", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
