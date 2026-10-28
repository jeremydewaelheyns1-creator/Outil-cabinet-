"""Les fichiers statiques passent la préparation de production (collectstatic avec manifeste).

Incident du 28/10/2026 : un fichier JavaScript copié depuis npm citait un fichier
« .map » absent ; la mise en ligne s'est arrêtée. Ce test rejoue la même vérification.
"""

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_production_static_files_build(tmp_path, settings):
    settings.STATIC_ROOT = tmp_path
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"},
    }
    call_command("collectstatic", interactive=False, verbosity=0)
    assert (tmp_path / "staticfiles.json").exists()
