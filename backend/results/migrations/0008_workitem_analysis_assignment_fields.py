from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("results", "0007_workitem_source_import_job"),
    ]

    operations = [
        migrations.AddField(
            model_name="workitem",
            name="analysis_code",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Analysis code snapshot for directly assigned or pipeline work.",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="workitem",
            name="required_fields",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Result requirements captured when the work is assigned.",
            ),
        ),
    ]
