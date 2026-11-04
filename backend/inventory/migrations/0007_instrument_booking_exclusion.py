from django.db import migrations


def add_exclusion(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('CREATE EXTENSION IF NOT EXISTS btree_gist')
        schema_editor.execute("""
            ALTER TABLE inventory_instrumentbooking
            ADD CONSTRAINT instrument_booking_no_overlap
            EXCLUDE USING gist (
                instrument_id WITH =,
                tstzrange(starts_at, ends_at, '[)') WITH &&
            ) WHERE (status = 'ACTIVE')
        """)


def remove_exclusion(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('ALTER TABLE inventory_instrumentbooking DROP CONSTRAINT IF EXISTS instrument_booking_no_overlap')


class Migration(migrations.Migration):
    dependencies = [('inventory', '0006_instrumentbooking')]
    operations = [migrations.RunPython(add_exclusion, remove_exclusion)]
