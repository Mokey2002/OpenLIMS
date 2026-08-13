import re

import django.db.models.deletion
from django.db import migrations, models


IMPORT_JOB_PATTERN = re.compile(r"Import Job\s+#?(\d+)", re.IGNORECASE)


def backfill_source_import_jobs(apps, schema_editor):
    WorkItem = apps.get_model("results", "WorkItem")
    ImportJob = apps.get_model("imports", "ImportJob")
    database = schema_editor.connection.alias
    job_projects = dict(
        ImportJob.objects.using(database).values_list("id", "project_id")
    )

    work_items = WorkItem.objects.using(database).filter(
        source_import_job__isnull=True,
    ).select_related("sample").only("id", "name", "notes", "sample__project_id")
    for work_item in work_items.iterator():
        job_id = None
        for value in (work_item.name, work_item.notes):
            match = IMPORT_JOB_PATTERN.search(str(value or ""))
            if match:
                candidate = int(match.group(1))
                job_project_id = job_projects.get(candidate)
                if candidate in job_projects and (
                    job_project_id is None
                    or job_project_id == work_item.sample.project_id
                ):
                    job_id = candidate
                    break
        if job_id:
            work_item.source_import_job_id = job_id
            work_item.save(
                update_fields=["source_import_job"],
                using=database,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0007_instrumentprofile_auto_detect_header_and_more"),
        ("results", "0006_workitem_assigned_to_workitem_created_by_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="workitem",
            name="source_import_job",
            field=models.ForeignKey(
                blank=True,
                help_text="Instrument import job that created this work item, when applicable.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="work_items",
                to="imports.importjob",
            ),
        ),
        migrations.RunPython(
            backfill_source_import_jobs,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
