import uuid

from django.db import migrations, models


MODEL_NAMES = [
    "Location",
    "Container",
    "InventoryItem",
    "InventoryLot",
    "InventoryReservation",
]


def populate_public_ids(apps, schema_editor):
    for model_name in MODEL_NAMES:
        Model = apps.get_model("inventory", model_name)
        for record in Model.objects.filter(public_id__isnull=True).iterator():
            record.public_id = uuid.uuid4()
            record.save(update_fields=["public_id"])


def nullable_public_id(model_name):
    return migrations.AddField(
        model_name=model_name,
        name="public_id",
        field=models.UUIDField(editable=False, null=True),
    )


def required_public_id(model_name):
    return migrations.AlterField(
        model_name=model_name,
        name="public_id",
        field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
    )


class Migration(migrations.Migration):
    dependencies = [("inventory", "0002_inventory_lots_and_hierarchy")]

    operations = [
        nullable_public_id("location"),
        nullable_public_id("container"),
        nullable_public_id("inventoryitem"),
        nullable_public_id("inventorylot"),
        nullable_public_id("inventoryreservation"),
        migrations.RunPython(populate_public_ids, migrations.RunPython.noop),
        required_public_id("location"),
        required_public_id("container"),
        required_public_id("inventoryitem"),
        required_public_id("inventorylot"),
        required_public_id("inventoryreservation"),
    ]
