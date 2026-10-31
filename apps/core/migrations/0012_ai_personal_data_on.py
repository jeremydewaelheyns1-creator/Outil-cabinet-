"""D-127 : l'assistant IA travaille en coulisse ; Mistral a confirmé le « zéro conservation »
le 31/10/2026 (compte de l'éditeur) : lecture des documents des clients autorisée."""

from django.db import migrations, models


def turn_on(apps, schema_editor):
    apps.get_model("core", "CabinetSettings").objects.update(ai_personal_data=True)


class Migration(migrations.Migration):
    dependencies = [("core", "0011_cabinetsettings_ai_personal_data_and_more")]

    operations = [
        migrations.AlterField(
            model_name="cabinetsettings",
            name="ai_personal_data",
            field=models.BooleanField(
                default=True,
                help_text="Actif : Mistral a confirmé le « zéro conservation » (Zero Data "
                "Retention) le 31/10/2026 pour le compte de l'éditeur (D-127).",
                verbose_name="l'assistant IA peut lire les documents des clients",
            ),
        ),
        migrations.AlterField(
            model_name="historicalcabinetsettings",
            name="ai_personal_data",
            field=models.BooleanField(
                default=True,
                help_text="Actif : Mistral a confirmé le « zéro conservation » (Zero Data "
                "Retention) le 31/10/2026 pour le compte de l'éditeur (D-127).",
                verbose_name="l'assistant IA peut lire les documents des clients",
            ),
        ),
        migrations.RunPython(turn_on, migrations.RunPython.noop),
    ]
