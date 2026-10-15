"""Une case par type de document (D-038) : on range les documents déjà classés."""

from django.db import migrations

NEW_CASE = {
    "identification_client": "identification-client",
    "identification_mandataire": "identification-mandataires",
    "procuration": "procuration",
    "fiche_risque": "fiche-risque",
    "declaration_ubo": "declaration-ubo",
}


def forwards(apps, schema_editor):
    Document = apps.get_model("documents", "Document")
    for doc_type, case in NEW_CASE.items():
        Document.objects.filter(doc_type=doc_type).exclude(case="").update(case=case)
    Document.objects.filter(case="anti-blanchiment").update(case="", folder="administratif")


class Migration(migrations.Migration):
    dependencies = [("documents", "0003_document_types")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
