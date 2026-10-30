"""La checklist gestionnaire commune de départ, définie par Jeremy le 30/10/2026 (D-112)."""

from django.db import migrations

ITEMS = [
    ("Vérification générale", "Balance relue, écarts importants avec l'an dernier expliqués"),
    ("Compte courant", "Solde du compte courant administrateur / associé justifié"),
    ("ATN", "Avantages de toute nature comptabilisés"),
    ("Intérêts fictifs", "Sur compte courant débiteur, au taux de l'année"),
    ("Dette fiscale estimée", "Provision ISOC de l'exercice, versements anticipés déduits"),
    ("Affectation du résultat N-1", "Passée selon l'AG (dividendes, réserves)"),
    ("Provisions", "Pécule de vacances, risques et charges"),
]


def seed(apps, schema_editor):
    CommonItem = apps.get_model("closing", "CommonItem")
    if CommonItem.objects.filter(kind="gestionnaire").exists():
        return
    for position, (label, hint) in enumerate(ITEMS, start=1):
        CommonItem.objects.create(kind="gestionnaire", label=label, hint=hint, position=position)


class Migration(migrations.Migration):
    dependencies = [("closing", "0003_gestionnaire")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
