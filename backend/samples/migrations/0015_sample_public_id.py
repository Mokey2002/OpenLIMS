import uuid

from django.db import migrations, models


def populate_public_ids(apps, schema_editor):
    Sample = apps.get_model("samples", "Sample")
    for sample in Sample.objects.filter(public_id__isnull=True).iterator():
        sample.public_id = uuid.uuid4()
        sample.save(update_fields=["public_id"])


class Migration(migrations.Migration):
    dependencies = [("samples", "0014_sample_custodian_samplecustodyevent_and_more")]

    operations = [
        migrations.AddField(
            model_name="sample",
            name="public_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(populate_public_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="sample",
            name="public_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
