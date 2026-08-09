import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("results", "0004_workitem_qc_status_workitem_review_note_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="result",
            name="unit",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="result",
            name="reference_min",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="result",
            name="reference_max",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="result",
            name="qc_rule",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="result",
            name="qc_passed",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="result",
            name="qc_failure_reason",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="result",
            name="qc_status",
            field=models.CharField(
                choices=[
                    ("PENDING_REVIEW", "Pending Review"),
                    ("APPROVED", "Approved"),
                    ("REJECTED", "Rejected"),
                    ("REOPENED", "Reopened"),
                ],
                default="PENDING_REVIEW",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="result",
            name="entered_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="entered_results",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="result",
            name="qc_assigned_to",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="assigned_qc_results",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="result",
            name="qc_reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="reviewed_results",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="result",
            name="qc_reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="result",
            name="qc_review_note",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="result",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
    ]
