import uuid

from django.db import migrations, models


def populate_public_ids(apps, schema_editor):
    PipelineRun = apps.get_model("pipelines", "PipelineRun")
    for run in PipelineRun.objects.filter(public_id__isnull=True).iterator():
        run.public_id = uuid.uuid4()
        run.save(update_fields=["public_id"])


class Migration(migrations.Migration):
    dependencies = [("pipelines", "0002_pipelinesteprun_activation_condition_and_more")]

    operations = [
        migrations.AddField(
            model_name="pipelinerun",
            name="public_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(populate_public_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="pipelinerun",
            name="public_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
