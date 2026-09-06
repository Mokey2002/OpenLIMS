from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("pipelines", "0003_pipelinerun_public_id"), ("custom_fields", "0002_sampleform")]
    operations = [
        migrations.AddField(model_name="pipelinetemplatestep", name="form", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="workflow_steps", to="custom_fields.sampleform")),
        migrations.AddField(model_name="pipelinesteprun", name="form_schema", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="pipelinesteprun", name="form_values", field=models.JSONField(blank=True, default=dict)),
    ]
