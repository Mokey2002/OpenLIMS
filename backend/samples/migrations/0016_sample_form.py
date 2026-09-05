from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("samples", "0015_sample_public_id")]
    operations = [
        migrations.AddField(model_name="sample", name="form_schema", field=models.JSONField(default=dict, blank=True)),
        migrations.AddField(model_name="sample", name="form_values", field=models.JSONField(default=dict, blank=True)),
    ]
