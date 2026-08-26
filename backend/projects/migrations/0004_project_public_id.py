import uuid

from django.db import migrations, models


def populate_public_ids(apps, schema_editor):
    Project = apps.get_model("projects", "Project")
    for project in Project.objects.filter(public_id__isnull=True).iterator():
        project.public_id = uuid.uuid4()
        project.save(update_fields=["public_id"])


class Migration(migrations.Migration):
    dependencies = [("projects", "0003_projectpost")]

    operations = [
        migrations.AddField(
            model_name="project",
            name="public_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(populate_public_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="project",
            name="public_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
