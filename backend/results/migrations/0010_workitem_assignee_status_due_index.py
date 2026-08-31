from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("results", "0009_workitem_result_public_ids"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="workitem",
            index=models.Index(
                fields=["assigned_to", "status", "due_at"],
                name="work_assignee_status_due_idx",
            ),
        ),
    ]
