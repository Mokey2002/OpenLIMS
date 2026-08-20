from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("samples", "0012_sample_batches_and_assignments"),
    ]

    operations = [
        migrations.AddField(
            model_name="sample",
            name="sample_type",
            field=models.CharField(
                default="GENERAL",
                help_text="Configurable sample classification used to select default pipelines.",
                max_length=64,
            ),
        ),
    ]
