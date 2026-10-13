"""Export de la démo statique (GitHub Pages)."""

import pytest
from django.core.management import CommandError, call_command

from apps.core.testing.factories import ClientFactory

pytestmark = pytest.mark.django_db


def test_export_demo_site(tmp_path):
    call_command("demo", stdout=__import__("io").StringIO())
    out = tmp_path / "site"
    call_command(
        "export_demo_site",
        str(out),
        "--base",
        "/Outil-cabinet-/",
        stdout=__import__("io").StringIO(),
    )
    home = (out / "index.html").read_text()
    assert "Démo — données inventées" in home
    assert 'href="/Outil-cabinet-/clients/"' in home
    assert (out / "clients" / "dossier" / "recherche" / "index.html").exists()
    assert (out / "nouveautes" / "index.html").exists()
    assert (out / "static" / "css" / "app.css").exists()
    assert not (out / "compte").exists()


def test_export_refuses_a_database_with_other_records(tmp_path):
    call_command("demo", stdout=__import__("io").StringIO())
    ClientFactory(reference="X999")
    with pytest.raises(CommandError):
        call_command("export_demo_site", str(tmp_path / "site"))
