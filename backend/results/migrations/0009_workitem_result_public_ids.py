import uuid

from django.db import migrations, models


def populate_public_ids(apps, schema_editor):
    for model_name in ["WorkItem", "Result"]:
        model = apps.get_model("results", model_name)
        for instance in model.objects.filter(public_id__isnull=True).iterator():
            instance.public_id = uuid.uuid4()
            instance.save(update_fields=["public_id"])


class Migration(migrations.Migration):
    dependencies = [("results", "0008_workitem_analysis_assignment_fields")]

    operations = [
        migrations.AddField(
            model_name="workitem",
            name="public_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="result",
            name="public_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(populate_public_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="workitem",
            name="public_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name="result",
            name="public_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
