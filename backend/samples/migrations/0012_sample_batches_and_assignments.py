# Generated for OpenLIMS v0.21.0 assistant sample operations.

import django.db.models.deletion
import django.db.models.functions.text
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("samples", "0011_sample_linked_projects"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SampleBatch",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("code", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_sample_batches",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sample_batches",
                        to="projects.project",
                    ),
                ),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.AddField(
            model_name="sample",
            name="assigned_to",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="assigned_samples",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="sample",
            name="batch",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="samples",
                to="samples.samplebatch",
            ),
        ),
        migrations.AddField(
            model_name="sample",
            name="status_changed_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="sample",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterField(
            model_name="sample",
            name="status",
            field=models.CharField(
                choices=[
                    ("RECEIVED", "Received"),
                    ("IN_PROGRESS", "In Progress"),
                    ("QC", "QC"),
                    ("REPORTED", "Reported"),
                    ("CANCELLED", "Cancelled"),
                    ("ARCHIVED", "Archived"),
                ],
                default="RECEIVED",
                max_length=32,
            ),
        ),
        migrations.AddConstraint(
            model_name="sample",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("sample_id"),
                name="samples_sample_id_ci_unique",
            ),
        ),
    ]
