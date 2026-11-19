from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflow_requests", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="assayrequesttype",
            name="portal_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="workflowrequestitem",
            name="submission_reference",
            field=models.CharField(blank=True, max_length=64),
        ),
    ]
