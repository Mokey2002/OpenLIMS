import uuid

from django.db import migrations, models


def populate_public_ids(apps, schema_editor):
    Sequence = apps.get_model("sequences", "Sequence")
    for sequence in Sequence.objects.filter(public_id__isnull=True).iterator():
        sequence.public_id = uuid.uuid4()
        sequence.save(update_fields=["public_id"])


class Migration(migrations.Migration):
    dependencies = [("sequences", "0002_sequence_import_job_sequence_source_metadata_and_more")]

    operations = [
        migrations.AddField(
            model_name="sequence",
            name="public_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(populate_public_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="sequence",
            name="public_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
