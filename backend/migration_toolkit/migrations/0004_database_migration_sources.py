# Generated for the guarded legacy database migration workflow.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("migration_toolkit", "0003_migrationrowrecord_raw_row_text_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MigrationDatabaseConnection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=128, unique=True)),
                ("engine", models.CharField(choices=[("POSTGRESQL", "PostgreSQL"), ("MYSQL", "MySQL / MariaDB"), ("SQLITE", "SQLite")], max_length=32)),
                ("host", models.CharField(blank=True, max_length=255)),
                ("port", models.PositiveIntegerField(blank=True, null=True)),
                ("database_name", models.CharField(help_text="Database name, or a path below MIGRATION_SQLITE_ROOT for SQLite.", max_length=512)),
                ("username", models.CharField(blank=True, max_length=128)),
                ("password_env_var", models.CharField(blank=True, help_text="Environment variable containing the read-only source password.", max_length=128)),
                ("ssl_mode", models.CharField(blank=True, default="prefer", max_length=32)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="migration_database_connections", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="MigrationDataset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=128)),
                ("entity_type", models.CharField(choices=[("PROJECT", "Projects"), ("USER", "Users"), ("SAMPLE", "Samples"), ("RESULT", "Historical results")], max_length=32)),
                ("source_schema", models.CharField(blank=True, max_length=128)),
                ("source_table", models.CharField(max_length=128)),
                ("source_key_column", models.CharField(max_length=128)),
                ("row_limit", models.PositiveIntegerField(default=10000)),
                ("active", models.BooleanField(default=True)),
                ("connection", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="datasets", to="migration_toolkit.migrationdatabaseconnection")),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="datasets", to="migration_toolkit.migrationprofile")),
            ],
            options={
                "ordering": ["entity_type", "id"],
                "unique_together": {("profile", "name")},
            },
        ),
        migrations.AlterField(
            model_name="migrationprofile",
            name="source_type",
            field=models.CharField(choices=[("CSV", "CSV"), ("DATABASE", "Database")], default="CSV", max_length=32),
        ),
        migrations.AddField(
            model_name="migrationfieldmapping",
            name="dataset",
            field=models.ForeignKey(blank=True, help_text="Database dataset for this mapping; leave empty for CSV profiles.", null=True, on_delete=django.db.models.deletion.CASCADE, related_name="field_mappings", to="migration_toolkit.migrationdataset"),
        ),
        migrations.AlterField(
            model_name="migrationfieldmapping",
            name="target_type",
            field=models.CharField(choices=[("PROJECT_CODE", "Project Code"), ("PROJECT_NAME", "Project Name"), ("SAMPLE_ID", "Sample ID"), ("EXTERNAL_ID", "External ID / Alias"), ("CUSTOM_FIELD", "Sample Custom Field"), ("WORK_ITEM_NAME", "Work Item Name"), ("RESULT_VALUE", "Result Value"), ("PROJECT_DESCRIPTION", "Project Description"), ("USER_USERNAME", "User Username"), ("USER_EMAIL", "User Email"), ("USER_FIRST_NAME", "User First Name"), ("USER_LAST_NAME", "User Last Name"), ("USER_ROLE", "User Role"), ("SAMPLE_TYPE", "Sample Type"), ("SAMPLE_STATUS", "Sample Status"), ("SAMPLE_CREATED_AT", "Sample Created At"), ("WORK_ITEM_TYPE", "Work Item Type"), ("WORK_ITEM_STATUS", "Work Item Status"), ("WORK_ITEM_CREATED_AT", "Work Item Created At"), ("RESULT_KEY", "Result Key"), ("RESULT_UNIT", "Result Unit"), ("RESULT_CREATED_AT", "Result Created At"), ("RESULT_QC_STATUS", "Result QC Status"), ("RESULT_ENTERED_BY", "Result Entered By"), ("RESULT_REFERENCE_MIN", "Result Reference Minimum"), ("RESULT_REFERENCE_MAX", "Result Reference Maximum")], max_length=64),
        ),
        migrations.AlterUniqueTogether(
            name="migrationfieldmapping",
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name="migrationfieldmapping",
            constraint=models.UniqueConstraint(condition=models.Q(("dataset__isnull", False)), fields=("profile", "dataset", "source_column", "target_type", "target_field"), name="migration_db_mapping_unique"),
        ),
        migrations.AddConstraint(
            model_name="migrationfieldmapping",
            constraint=models.UniqueConstraint(condition=models.Q(("dataset__isnull", True)), fields=("profile", "source_column", "target_type", "target_field"), name="migration_csv_mapping_unique"),
        ),
        migrations.AddField(
            model_name="migrationjob",
            name="source_connection",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="migration_jobs", to="migration_toolkit.migrationdatabaseconnection"),
        ),
        migrations.AddField(
            model_name="migrationjob",
            name="source_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="migrationjob",
            name="preview_fingerprint",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="migrationjob",
            name="committed_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="committed_migration_jobs", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="migrationjob",
            name="confirmed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="migrationrowrecord",
            name="source_dataset",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="row_records", to="migration_toolkit.migrationdataset"),
        ),
        migrations.AddField(
            model_name="migrationrowrecord",
            name="entity_type",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="migrationrowrecord",
            name="source_key",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterUniqueTogether(
            name="migrationrowrecord",
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name="migrationrowrecord",
            constraint=models.UniqueConstraint(condition=models.Q(("source_dataset__isnull", False)), fields=("migration_job", "source_dataset", "row_number"), name="migration_db_row_unique"),
        ),
        migrations.AddConstraint(
            model_name="migrationrowrecord",
            constraint=models.UniqueConstraint(condition=models.Q(("source_dataset__isnull", True)), fields=("migration_job", "row_number"), name="migration_csv_row_unique"),
        ),
    ]
