import uuid

from django.db import migrations, models


def populate_public_ids(apps, schema_editor):
    SOPDocument = apps.get_model("assistant", "SOPDocument")
    for document in SOPDocument.objects.filter(public_id__isnull=True).iterator():
        document.public_id = uuid.uuid4()
        document.save(update_fields=["public_id"])


class Migration(migrations.Migration):
    dependencies = [("assistant", "0006_assistantinteraction_assistantfeedback")]

    operations = [
        migrations.AddField(
            model_name="sopdocument",
            name="public_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(populate_public_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="sopdocument",
            name="public_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
