"""Le journal des consultations ne peut pas non plus être vidé par TRUNCATE."""

from django.db import migrations

FORBID_TRUNCATE = """
CREATE OR REPLACE FUNCTION core_accesslog_forbid_truncate() RETURNS trigger AS $$
BEGIN
    IF current_setting('app.allow_audit_purge', true) = 'on' THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'Le journal des consultations ne peut pas être vidé.'
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER core_accesslog_no_truncate
    BEFORE TRUNCATE ON core_accesslog
    FOR EACH STATEMENT EXECUTE FUNCTION core_accesslog_forbid_truncate();
"""

ALLOW_TRUNCATE = """
DROP TRIGGER IF EXISTS core_accesslog_no_truncate ON core_accesslog;
DROP FUNCTION IF EXISTS core_accesslog_forbid_truncate();
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0002_postgres_setup")]

    operations = [migrations.RunSQL(FORBID_TRUNCATE, ALLOW_TRUNCATE)]
