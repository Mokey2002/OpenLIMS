# Generated for OpenLIMS v0.21.0 assistant sample operations.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="assistantaction",
            name="action_type",
            field=models.CharField(
                choices=[
                    ("RUN_BLAST", "Run BLAST"),
                    ("RUN_ALIGNMENT", "Run alignment"),
                    (
                        "CREATE_MIGRATION_MAPPINGS",
                        "Create migration mappings",
                    ),
                    ("QUEUE_REPORT", "Queue report"),
                    ("QUEUE_IMPORT", "Queue import"),
                    ("CREATE_SAMPLES", "Create samples"),
                    ("BULK_SAMPLE_UPDATE", "Bulk sample update"),
                ],
                max_length=40,
            ),
        ),
    ]
