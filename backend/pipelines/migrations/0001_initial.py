import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("assistant", "0006_assistantinteraction_assistantfeedback"),
        ("projects", "0003_projectpost"),
        ("results", "0007_workitem_source_import_job"),
        ("samples", "0013_sample_sample_type"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AnalysisDefinition",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=128)),
                ("category", models.CharField(blank=True, max_length=64)),
                ("description", models.TextField(blank=True)),
                ("required_fields", models.JSONField(blank=True, default=list, help_text="Result fields required before a pipeline step can complete.")),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_analysis_definitions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="ProcedureDefinition",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=64)),
                ("name", models.CharField(max_length=128)),
                ("version", models.CharField(default="1", max_length=32)),
                ("instructions", models.TextField(blank=True)),
                ("estimated_duration_minutes", models.PositiveIntegerField(default=60)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("analysis", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="procedures", to="pipelines.analysisdefinition")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_procedure_definitions", to=settings.AUTH_USER_MODEL)),
                ("sop_document", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="procedure_definitions", to="assistant.sopdocument")),
            ],
            options={"ordering": ["code", "version"]},
        ),
        migrations.CreateModel(
            name="PipelineTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=128)),
                ("description", models.TextField(blank=True)),
                ("active", models.BooleanField(default=True)),
                ("is_default", models.BooleanField(default=False)),
                ("default_sample_type", models.CharField(blank=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_pipeline_templates", to=settings.AUTH_USER_MODEL)),
                ("default_project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="default_pipeline_templates", to="projects.project")),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="PipelineRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("template_code", models.CharField(max_length=64)),
                ("template_name", models.CharField(max_length=128)),
                ("status", models.CharField(choices=[("ACTIVE", "Active"), ("COMPLETED", "Completed"), ("BLOCKED", "Blocked"), ("CANCELLED", "Cancelled")], default="ACTIVE", max_length=16)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("sample", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="pipeline_runs", to="samples.sample")),
                ("started_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="started_pipeline_runs", to=settings.AUTH_USER_MODEL)),
                ("template", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="runs", to="pipelines.pipelinetemplate")),
            ],
            options={"ordering": ["-started_at"]},
        ),
        migrations.CreateModel(
            name="PipelineTemplateStep",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position", models.PositiveIntegerField()),
                ("name", models.CharField(blank=True, help_text="Optional display name. The procedure name is used when blank.", max_length=128)),
                ("requires_qc", models.BooleanField(default=False)),
                ("procedure", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="pipeline_steps", to="pipelines.proceduredefinition")),
                ("template", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="steps", to="pipelines.pipelinetemplate")),
            ],
            options={"ordering": ["position"]},
        ),
        migrations.CreateModel(
            name="PipelineStepRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position", models.PositiveIntegerField()),
                ("name", models.CharField(max_length=128)),
                ("analysis_code", models.CharField(max_length=64)),
                ("procedure_code", models.CharField(max_length=64)),
                ("procedure_version", models.CharField(max_length=32)),
                ("work_type", models.CharField(max_length=64)),
                ("required_fields", models.JSONField(blank=True, default=list)),
                ("requires_qc", models.BooleanField(default=False)),
                ("estimated_duration_minutes", models.PositiveIntegerField(default=60)),
                ("status", models.CharField(choices=[("BLOCKED", "Blocked"), ("READY", "Ready"), ("IN_PROGRESS", "In Progress"), ("AWAITING_QC", "Awaiting QC"), ("COMPLETED", "Completed"), ("FAILED", "Failed"), ("CANCELLED", "Cancelled")], default="BLOCKED", max_length=16)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("failure_reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("pipeline_run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="steps", to="pipelines.pipelinerun")),
                ("template_step", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="step_runs", to="pipelines.pipelinetemplatestep")),
                ("work_item", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="pipeline_step_run", to="results.workitem")),
            ],
            options={"ordering": ["position"]},
        ),
        migrations.AddConstraint(
            model_name="analysisdefinition",
            constraint=models.UniqueConstraint(Lower("code"), name="pipelines_analysis_code_ci_unique"),
        ),
        migrations.AddConstraint(
            model_name="proceduredefinition",
            constraint=models.UniqueConstraint(Lower("code"), "version", name="pipelines_procedure_code_version_ci_unique"),
        ),
        migrations.AddConstraint(
            model_name="pipelinetemplate",
            constraint=models.UniqueConstraint(Lower("code"), name="pipelines_template_code_ci_unique"),
        ),
        migrations.AddConstraint(
            model_name="pipelinerun",
            constraint=models.UniqueConstraint(condition=models.Q(("status__in", ["ACTIVE", "BLOCKED"])), fields=("sample",), name="pipelines_one_active_run_per_sample"),
        ),
        migrations.AddConstraint(
            model_name="pipelinetemplatestep",
            constraint=models.UniqueConstraint(fields=("template", "position"), name="pipelines_template_step_position_unique"),
        ),
        migrations.AddConstraint(
            model_name="pipelinesteprun",
            constraint=models.UniqueConstraint(fields=("pipeline_run", "position"), name="pipelines_run_step_position_unique"),
        ),
    ]
