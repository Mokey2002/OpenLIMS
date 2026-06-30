import csv
import io

from django.db import transaction

from custom_fields.models import FieldDefinition, FieldValue
from events.models import Event
from projects.models import Project
from results.models import Result, WorkItem
from samples.access import validate_sample_project_assignment
from samples.models import Sample

from .models import MigrationFieldMapping, SampleExternalID


def normalize_bool(value):
    normalized = str(value or "").strip().lower()

    if normalized in ["true", "1", "yes", "y", "pass", "ok"]:
        return True

    if normalized in ["false", "0", "no", "n", "fail"]:
        return False

    return None


def normalize_value(raw_value, value_type):
    if raw_value in [None, ""]:
        return None

    if value_type == MigrationFieldMapping.VALUE_TYPE_NUMBER:
        return float(raw_value)

    if value_type == MigrationFieldMapping.VALUE_TYPE_BOOLEAN:
        return normalize_bool(raw_value)

    return str(raw_value).strip()


def read_csv(uploaded_file):
    uploaded_file.seek(0)
    decoded = uploaded_file.read().decode("utf-8-sig")
    uploaded_file.seek(0)

    reader = csv.DictReader(io.StringIO(decoded))
    rows = list(reader)

    return rows, reader.fieldnames or []


def mappings_by_type(profile):
    mappings = profile.field_mappings.all().order_by("id")

    grouped = {}

    for mapping in mappings:
        grouped.setdefault(mapping.target_type, []).append(mapping)

    return grouped


def get_first_value(row, mappings, target_type):
    for mapping in mappings.get(target_type, []):
        value = row.get(mapping.source_column)

        if value not in [None, ""]:
            return str(value).strip(), mapping

    return None, None


def build_preview(profile, uploaded_file, default_project=None):
    rows, fieldnames = read_csv(uploaded_file)
    mappings = mappings_by_type(profile)
    mapped_columns = {
        mapping.source_column
        for mapping_list in mappings.values()
        for mapping in mapping_list
    }

    unmapped_columns = [
        column for column in fieldnames
        if column not in mapped_columns
    ]

    projects_to_create = set()
    projects_matched = set()
    samples_to_create = set()
    samples_matched = set()
    external_ids_to_create = 0
    custom_fields_to_create = set()
    results_to_create = 0
    skipped_rows = []
    preview_rows = []

    for row_number, row in enumerate(rows, start=1):
        row_errors = []

        sample_code, _ = get_first_value(
            row,
            mappings,
            MigrationFieldMapping.TARGET_SAMPLE_ID,
        )

        if not sample_code:
            row_errors.append("Missing mapped sample ID.")

        project_code, _ = get_first_value(
            row,
            mappings,
            MigrationFieldMapping.TARGET_PROJECT_CODE,
        )

        project_name, _ = get_first_value(
            row,
            mappings,
            MigrationFieldMapping.TARGET_PROJECT_NAME,
        )

        target_project = None

        if project_code:
            target_project = Project.objects.filter(code=project_code).first()

            if target_project:
                projects_matched.add(project_code)
            else:
                projects_to_create.add(project_code)

        elif default_project:
            target_project = default_project
            projects_matched.add(default_project.code)

        elif project_name:
            target_project = Project.objects.filter(name=project_name).first()

            if target_project:
                projects_matched.add(target_project.code)
            else:
                projects_to_create.add(project_name)

        else:
            row_errors.append("Missing project mapping or default project.")

        if sample_code:
            existing_sample = Sample.objects.filter(sample_id=sample_code).first()

            if existing_sample:
                samples_matched.add(sample_code)
            else:
                samples_to_create.add(sample_code)

        external_id_mappings = mappings.get(
            MigrationFieldMapping.TARGET_EXTERNAL_ID,
            [],
        )
        custom_field_mappings = mappings.get(
            MigrationFieldMapping.TARGET_CUSTOM_FIELD,
            [],
        )
        result_mappings = mappings.get(
            MigrationFieldMapping.TARGET_RESULT_VALUE,
            [],
        )

        external_ids_to_create += len([
            mapping for mapping in external_id_mappings
            if row.get(mapping.source_column)
        ])

        for mapping in custom_field_mappings:
            if row.get(mapping.source_column):
                custom_fields_to_create.add(mapping.target_field or mapping.source_column)

        for mapping in result_mappings:
            if row.get(mapping.source_column):
                results_to_create += 1

        if row_errors:
            skipped_rows.append({
                "row": row_number,
                "sample_id": sample_code,
                "errors": row_errors,
            })

        preview_rows.append({
            "row": row_number,
            "sample_id": sample_code,
            "project": project_code or project_name or (
                default_project.code if default_project else None
            ),
            "will_skip": bool(row_errors),
            "errors": row_errors,
        })

    return {
        "rows_processed": len(rows),
        "projects_to_create": sorted(projects_to_create),
        "projects_matched": sorted(projects_matched),
        "samples_to_create": sorted(samples_to_create),
        "samples_matched": sorted(samples_matched),
        "external_ids_to_create": external_ids_to_create,
        "custom_fields_to_create": sorted(custom_fields_to_create),
        "results_to_create": results_to_create,
        "skipped_rows": skipped_rows,
        "unmapped_columns": unmapped_columns,
        "preview_rows": preview_rows[:50],
        "fieldnames": fieldnames,
    }


def set_result_value(work_item, key, raw_value, value_type):
    normalized = normalize_value(raw_value, value_type)

    defaults = {
        "value_type": value_type,
        "value_string": "",
        "value_number": None,
        "value_boolean": None,
    }

    if value_type == MigrationFieldMapping.VALUE_TYPE_NUMBER:
        defaults["value_number"] = normalized
    elif value_type == MigrationFieldMapping.VALUE_TYPE_BOOLEAN:
        defaults["value_boolean"] = normalized
    else:
        defaults["value_string"] = "" if normalized is None else str(normalized)

    Result.objects.update_or_create(
        work_item=work_item,
        key=key,
        defaults=defaults,
    )


@transaction.atomic
def apply_migration(profile, uploaded_file, actor, default_project=None):
    rows, fieldnames = read_csv(uploaded_file)
    mappings = mappings_by_type(profile)

    projects_created = []
    samples_created = []
    samples_matched = []
    external_ids_created = []
    custom_values_created = 0
    results_created = 0
    skipped_rows = []

    for row_number, row in enumerate(rows, start=1):
        sample_code, _ = get_first_value(
            row,
            mappings,
            MigrationFieldMapping.TARGET_SAMPLE_ID,
        )

        if not sample_code:
            skipped_rows.append({
                "row": row_number,
                "reason": "Missing mapped sample ID.",
            })
            continue

        project_code, _ = get_first_value(
            row,
            mappings,
            MigrationFieldMapping.TARGET_PROJECT_CODE,
        )

        project_name, _ = get_first_value(
            row,
            mappings,
            MigrationFieldMapping.TARGET_PROJECT_NAME,
        )

        project = None

        if project_code:
            project, created = Project.objects.get_or_create(
                code=project_code,
                defaults={
                    "name": project_name or project_code,
                    "description": f"Migrated from {profile.source_system}",
                },
            )

            if created:
                projects_created.append(project.code)

        elif default_project:
            project = default_project

        elif project_name:
            project, created = Project.objects.get_or_create(
                name=project_name,
                defaults={
                    "code": project_name.upper().replace(" ", "-")[:64],
                    "description": f"Migrated from {profile.source_system}",
                },
            )

            if created:
                projects_created.append(project.code)

        if project is None:
            skipped_rows.append({
                "row": row_number,
                "sample_id": sample_code,
                "reason": "Missing project mapping or default project.",
            })
            continue

        validate_sample_project_assignment(actor, project)

        sample, sample_created = Sample.objects.get_or_create(
            sample_id=sample_code,
            defaults={
                "status": Sample.STATUS_RECEIVED,
                "project": project,
                "created_by": actor,
            },
        )

        if sample_created:
            samples_created.append(sample.sample_id)
        else:
            samples_matched.append(sample.sample_id)

        for mapping in mappings.get(MigrationFieldMapping.TARGET_EXTERNAL_ID, []):
            external_value = row.get(mapping.source_column)

            if not external_value:
                continue

            external_id, created = SampleExternalID.objects.get_or_create(
                source_system=profile.source_system,
                external_id=str(external_value).strip(),
                label=mapping.target_field or mapping.source_column,
                defaults={
                    "sample": sample,
                    "metadata": {
                        "migration_profile_id": profile.id,
                        "source_column": mapping.source_column,
                    },
                },
            )

            if created:
                external_ids_created.append(external_id.external_id)

        for mapping in mappings.get(MigrationFieldMapping.TARGET_CUSTOM_FIELD, []):
            raw_value = row.get(mapping.source_column)

            if raw_value in [None, ""]:
                continue

            field_name = mapping.target_field or mapping.source_column

            field_definition, _ = FieldDefinition.objects.get_or_create(
                entity_type="Sample",
                name=field_name,
                defaults={
                    "label": field_name.replace("_", " ").title(),
                    "data_type": "string",
                    "rules": {
                        "source_system": profile.source_system,
                    },
                },
            )

            FieldValue.objects.update_or_create(
                field_definition=field_definition,
                entity_type="Sample",
                entity_id=str(sample.id),
                defaults={
                    "value": normalize_value(raw_value, mapping.value_type),
                },
            )

            custom_values_created += 1

        work_item_name, _ = get_first_value(
            row,
            mappings,
            MigrationFieldMapping.TARGET_WORK_ITEM_NAME,
        )
        work_item_name = work_item_name or "Migrated Results"

        result_mappings = mappings.get(MigrationFieldMapping.TARGET_RESULT_VALUE, [])

        if result_mappings:
            work_item, _ = WorkItem.objects.get_or_create(
                sample=sample,
                name=work_item_name,
                defaults={
                    "status": WorkItem.STATUS_COMPLETED,
                    "notes": f"Migrated from {profile.source_system}.",
                },
            )

            for mapping in result_mappings:
                raw_value = row.get(mapping.source_column)

                if raw_value in [None, ""]:
                    continue

                result_key = mapping.target_field or mapping.source_column

                set_result_value(
                    work_item=work_item,
                    key=result_key,
                    raw_value=raw_value,
                    value_type=mapping.value_type,
                )

                results_created += 1

    summary = {
        "rows_processed": len(rows),
        "projects_created": sorted(set(projects_created)),
        "samples_created": sorted(set(samples_created)),
        "samples_matched": sorted(set(samples_matched)),
        "external_ids_created": len(external_ids_created),
        "custom_values_created": custom_values_created,
        "results_created": results_created,
        "skipped_rows": skipped_rows,
        "source_system": profile.source_system,
    }

    Event.objects.create(
        entity_type="MigrationProfile",
        entity_id=str(profile.id),
        action="MIGRATION_IMPORTED",
        actor=actor,
        payload=summary,
    )

    return summary
