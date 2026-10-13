"""Extensions PostgreSQL, protection du journal des consultations, données de départ."""

from django.contrib.postgres.operations import TrigramExtension, UnaccentExtension
from django.db import migrations

PROTECT_ACCESS_LOG = """
CREATE OR REPLACE FUNCTION core_accesslog_protect() RETURNS trigger AS $$
BEGIN
    -- Seule exception : la purge légale (après le délai de conservation), qui doit être
    -- explicitement autorisée dans la transaction par SET LOCAL app.allow_audit_purge = 'on'.
    IF TG_OP = 'DELETE' AND current_setting('app.allow_audit_purge', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Le journal des consultations est en lecture seule (%).', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER core_accesslog_readonly
    BEFORE UPDATE OR DELETE ON core_accesslog
    FOR EACH ROW EXECUTE FUNCTION core_accesslog_protect();
"""

UNPROTECT_ACCESS_LOG = """
DROP TRIGGER IF EXISTS core_accesslog_readonly ON core_accesslog;
DROP FUNCTION IF EXISTS core_accesslog_protect();
"""

DEFAULT_PROFILES = [
    (
        "Collaborateur",
        "Gère les dossiers de ses portefeuilles.",
        ["clients.edit"],
    ),
    (
        "Responsable",
        "Collaborateur avec accès aux données sensibles et aux exports.",
        ["clients.edit", "clients.sensitive", "data.export", "aml.view"],
    ),
    (
        "Responsable anti-blanchiment (AMLCO)",
        "Décide en matière d'anti-blanchiment et consulte le journal.",
        ["clients.edit", "clients.sensitive", "aml.view", "aml.decide", "audit.view"],
    ),
]


def create_defaults(apps, schema_editor):
    Portfolio = apps.get_model("core", "Portfolio")
    SecurityProfile = apps.get_model("core", "SecurityProfile")
    Portfolio.objects.get_or_create(name="Cabinet", defaults={"is_private": False, "order": 0})
    for name, description, capabilities in DEFAULT_PROFILES:
        SecurityProfile.objects.get_or_create(
            name=name, defaults={"description": description, "capabilities": capabilities}
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [
        UnaccentExtension(),
        TrigramExtension(),
        migrations.RunSQL(PROTECT_ACCESS_LOG, UNPROTECT_ACCESS_LOG),
        migrations.RunPython(create_defaults, migrations.RunPython.noop),
    ]
