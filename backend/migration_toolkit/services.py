import csv
import io
import json
import re

from django.db import transaction

from custom_fields.models import FieldDefinition, FieldValue
from events.models import Event
from projects.models import Project
from results.models import Result, WorkItem
from samples.access import validate_sample_project_assignment
from samples.models import Sample

from .models import MigrationFieldMapping, MigrationRowRecord, SampleExternalID


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



def get_mapped_columns(mappings):
    return {
        mapping.source_column
        for mapping_list in mappings.values()
        for mapping in mapping_list
    }


def get_unmapped_data(row, mapped_columns):
    return {
        key: value
        for key, value in row.items()
        if key not in mapped_columns and value not in [None, ""]
    }


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



def resolve_project_for_migration(project_code, project_name, default_project=None):
    """
    Resolve projects safely during migration.

    Priority:
    1. Use default selected project if provided.
    2. Match by OpenLIMS project code.
    3. Match by existing project name.
    4. Create project only if neither code nor name already exists.
    """
    if default_project:
        return default_project, False, "default_project"

    project_code = str(project_code or "").strip()
    project_name = str(project_name or "").strip()

    if project_code:
        project = Project.objects.filter(code=project_code).first()

        if project:
            return project, False, "matched_code"

    if project_name:
        project = Project.objects.filter(name=project_name).first()

        if project:
            return project, False, "matched_name"

    if project_code:
        project = Project.objects.create(
            code=project_code,
            name=project_name or project_code,
            description="Migrated legacy project.",
        )
        return project, True, "created_code"

    if project_name:
        base_code = project_name.upper().replace(" ", "-")[:64]
        code = base_code
        counter = 2

        while Project.objects.filter(code=code).exists():
            suffix = f"-{counter}"
            code = f"{base_code[:64-len(suffix)]}{suffix}"
            counter += 1

        project = Project.objects.create(
            code=code,
            name=project_name,
            description="Migrated legacy project.",
        )
        return project, True, "created_name"

    return None, False, "missing"

def build_preview(profile, uploaded_file, default_project=None, preview_limit=100):
    rows, fieldnames = read_csv(uploaded_file)
    total_rows = len(rows)
    mappings = mappings_by_type(profile)
    mapped_columns = get_mapped_columns(mappings)

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
            "project_id": target_project.id if target_project else (
                default_project.id if default_project else None
            ),
            "project": project_code or project_name or (
                default_project.code if default_project else None
            ),
            "unmapped_data": get_unmapped_data(row, mapped_columns),
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
        "preview_rows": preview_rows[:preview_limit],
        "preview_limit": preview_limit,
        "preview_rows_returned": min(len(preview_rows), preview_limit),
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




def normalize_column_name(column):
    normalized = str(column or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized


def infer_value_type_for_column(normalized_column):
    boolean_keywords = [
        "pass",
        "fail",
        "passed",
        "failed",
        "valid",
        "approved",
        "detected",
        "positive",
        "negative",
    ]

    numeric_keywords = [
        "value",
        "result",
        "concentration",
        "count",
        "score",
        "ct",
        "delta_ct",
        "q30",
        "purity",
        "yield",
        "rin",
        "length",
        "size",
        "abs",
        "od",
        "eu_ml",
        "recovery",
        "ng_ul",
        "volume",
        "intensity",
        "mz",
        "rt",
        "percent",
        "percentage",
        "ratio",
    ]

    if any(keyword in normalized_column for keyword in boolean_keywords):
        return MigrationFieldMapping.VALUE_TYPE_BOOLEAN

    if any(keyword in normalized_column for keyword in numeric_keywords):
        return MigrationFieldMapping.VALUE_TYPE_NUMBER

    return MigrationFieldMapping.VALUE_TYPE_STRING


def infer_mappings_for_column(column, fieldnames):
    normalized = normalize_column_name(column)
    normalized_fieldnames = {normalize_column_name(item) for item in fieldnames}

    suggestions = []

    def add(target_type, target_field="", value_type=None, required=False):
        suggestions.append({
            "source_column": column,
            "target_type": target_type,
            "target_field": target_field,
            "value_type": value_type or MigrationFieldMapping.VALUE_TYPE_STRING,
            "required": required,
        })

    # Project identifiers
    if normalized == "project_code":
        add(MigrationFieldMapping.TARGET_PROJECT_CODE, required=False)
        return suggestions

    if normalized in ["project_name", "study_name"]:
        add(MigrationFieldMapping.TARGET_PROJECT_NAME, required=False)
        return suggestions

    # Legacy project IDs should be preserved, not treated as OpenLIMS project codes.
    if normalized in ["project_id", "study_id", "legacy_project_id", "old_project_id"]:
        add(
            MigrationFieldMapping.TARGET_CUSTOM_FIELD,
            target_field=normalized,
            value_type=MigrationFieldMapping.VALUE_TYPE_STRING,
            required=False,
        )
        return suggestions

    # Sample identifiers
    if normalized == "sample_id":
        add(MigrationFieldMapping.TARGET_SAMPLE_ID, required=True)
        return suggestions

    if normalized in ["specimen_id", "aliquot_id", "tube_id", "sample_code", "legacy_sample_id"]:
        if "sample_id" not in normalized_fieldnames:
            add(MigrationFieldMapping.TARGET_SAMPLE_ID, required=True)

        add(
            MigrationFieldMapping.TARGET_EXTERNAL_ID,
            target_field=normalized,
            value_type=MigrationFieldMapping.VALUE_TYPE_STRING,
            required=False,
        )
        return suggestions

    if normalized in ["external_id", "legacy_id", "legacy_specimen_id"]:
        add(
            MigrationFieldMapping.TARGET_EXTERNAL_ID,
            target_field=normalized,
            value_type=MigrationFieldMapping.VALUE_TYPE_STRING,
            required=False,
        )
        return suggestions

    # Work item / assay identifiers
    if normalized in ["assay", "assay_name", "test", "test_name", "panel", "panel_name", "analyte"]:
        add(MigrationFieldMapping.TARGET_WORK_ITEM_NAME, required=False)
        return suggestions

    # Be conservative with result values. Only obvious result/value columns become results.
    result_columns = [
        "result",
        "result_value",
        "value",
        "measurement",
        "measurement_value",
        "concentration",
        "read_count",
        "mean_q_score",
        "percent_q30",
        "ct_value",
        "delta_ct",
        "purity",
        "yield",
        "rin",
        "endotoxin_eu_ml",
        "spike_recovery_percent",
        "quality_score",
        "abs_450",
        "abs_570",
        "ng_ul",
    ]

    if normalized in result_columns:
        add(
            MigrationFieldMapping.TARGET_RESULT_VALUE,
            target_field=normalized,
            value_type=infer_value_type_for_column(normalized),
            required=False,
        )
        return suggestions

    # Default behavior: unknown legacy columns become sample custom fields.
    add(
        MigrationFieldMapping.TARGET_CUSTOM_FIELD,
        target_field=normalized,
        value_type=MigrationFieldMapping.VALUE_TYPE_STRING,
        required=False,
    )

    return suggestions


def suggest_field_mappings(profile, uploaded_file):
    rows, fieldnames = read_csv(uploaded_file)

    created = []
    existing = []

    for column in fieldnames:
        suggestions = infer_mappings_for_column(column, fieldnames)

        for suggestion in suggestions:
            mapping, was_created = MigrationFieldMapping.objects.get_or_create(
                profile=profile,
                source_column=suggestion["source_column"],
                target_type=suggestion["target_type"],
                target_field=suggestion.get("target_field", ""),
                defaults={
                    "value_type": suggestion.get(
                        "value_type",
                        MigrationFieldMapping.VALUE_TYPE_STRING,
                    ),
                    "required": suggestion.get("required", False),
                },
            )

            item = {
                "id": mapping.id,
                "source_column": mapping.source_column,
                "target_type": mapping.target_type,
                "target_field": mapping.target_field,
                "value_type": mapping.value_type,
                "required": mapping.required,
            }

            if was_created:
                created.append(item)
            else:
                existing.append(item)

    return {
        "fieldnames": fieldnames,
        "created_count": len(created),
        "existing_count": len(existing),
        "created": created,
        "existing": existing,
    }




def create_sample_custom_field_value(sample, field_name, raw_value, value_type, profile):
    field_name = normalize_column_name(field_name)

    if not field_name or raw_value in [None, ""]:
        return 0

    field_definition, _ = FieldDefinition.objects.get_or_create(
        entity_type="Sample",
        name=field_name,
        defaults={
            "label": field_name.replace("_", " ").title(),
            "data_type": "string",
            "rules": {
                "source_system": profile.source_system,
                "created_by": "migration_toolkit",
            },
        },
    )

    FieldValue.objects.update_or_create(
        field_definition=field_definition,
        entity_type="Sample",
        entity_id=str(sample.id),
        defaults={
            "value": normalize_value(raw_value, value_type),
        },
    )

    return 1


def create_unmapped_data_as_custom_fields(sample, unmapped_data, profile):
    created_count = 0

    for key, value in (unmapped_data or {}).items():
        created_count += create_sample_custom_field_value(
            sample=sample,
            field_name=key,
            raw_value=value,
            value_type=MigrationFieldMapping.VALUE_TYPE_STRING,
            profile=profile,
        )

    return created_count


def apply_migration(
    profile,
    uploaded_file,
    actor,
    default_project=None,
    job=None,
    progress_callback=None,
):
    rows, fieldnames = read_csv(uploaded_file)
    mappings = mappings_by_type(profile)
    mapped_columns = get_mapped_columns(mappings)

    projects_created = []
    samples_created = []
    samples_matched = []
    external_ids_created = []
    custom_values_created = 0
    results_created = 0
    skipped_rows = []
    row_records_created = 0
    unmapped_rows_preserved = 0

    def report_progress(row_number=0):
        if not progress_callback:
            return

        percent = 100 if total_rows == 0 else round((row_number / total_rows) * 100, 2)

        progress_callback({
            "processed_rows": row_number,
            "total_rows": total_rows,
            "percent": percent,
            "samples_created": len(samples_created),
            "samples_matched": len(samples_matched),
            "results_created": results_created,
            "custom_values_created": custom_values_created,
            "row_records_created": row_records_created,
            "skipped_rows": len(skipped_rows),
        })

    report_progress(0)

    for row_number, row in enumerate(rows, start=1):
        unmapped_data = get_unmapped_data(row, mapped_columns)

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

            if job:
                MigrationRowRecord.objects.create(
                    migration_job=job,
                    row_number=row_number,
                    raw_row=row,
                    raw_row_text=json.dumps(row, sort_keys=True),
                    unmapped_data=unmapped_data,
                    status=MigrationRowRecord.STATUS_SKIPPED,
                    errors=["Missing mapped sample ID."],
                )
                row_records_created += 1
                if unmapped_data:
                    unmapped_rows_preserved += 1

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

        project, created, project_resolution = resolve_project_for_migration(
            project_code=project_code,
            project_name=project_name,
            default_project=default_project,
        )

        if created and project:
            projects_created.append(project.code)

        if project is None:
            skipped_rows.append({
                "row": row_number,
                "sample_id": sample_code,
                "reason": "Missing project mapping or default project.",
            })

            if job:
                MigrationRowRecord.objects.create(
                    migration_job=job,
                    row_number=row_number,
                    project_code=project_code or "",
                    project_name=project_name or "",
                    sample_code=sample_code or "",
                    raw_row=row,
                    raw_row_text=json.dumps(row, sort_keys=True),
                    unmapped_data=unmapped_data,
                    status=MigrationRowRecord.STATUS_SKIPPED,
                    errors=["Missing project mapping or default project."],
                )
                row_records_created += 1
                if unmapped_data:
                    unmapped_rows_preserved += 1

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

        # Any columns still unmapped are preserved as string custom fields.
        custom_values_created += create_unmapped_data_as_custom_fields(
            sample=sample,
            unmapped_data=unmapped_data,
            profile=profile,
        )

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

                try:
                    set_result_value(
                        work_item=work_item,
                        key=result_key,
                        raw_value=raw_value,
                        value_type=mapping.value_type,
                    )

                    results_created += 1
                except (TypeError, ValueError):
                    custom_values_created += create_sample_custom_field_value(
                        sample=sample,
                        field_name=result_key,
                        raw_value=raw_value,
                        value_type=MigrationFieldMapping.VALUE_TYPE_STRING,
                        profile=profile,
                    )

                    skipped_rows.append({
                        "row": row_number,
                        "sample_id": sample_code,
                        "source_column": mapping.source_column,
                        "reason": (
                            "Could not convert value for mapped result. "
                            "Saved as string custom field instead."
                        ),
                    })

        if job:
            MigrationRowRecord.objects.create(
                migration_job=job,
                project=project,
                sample=sample,
                row_number=row_number,
                project_code=project.code if project else project_code or "",
                project_name=project.name if project else project_name or "",
                sample_code=sample.sample_id if sample else sample_code or "",
                raw_row=row,
                raw_row_text=json.dumps(row, sort_keys=True),
                unmapped_data=unmapped_data,
                status=MigrationRowRecord.STATUS_IMPORTED,
                errors=[],
            )
            row_records_created += 1
            if unmapped_data:
                unmapped_rows_preserved += 1

        if row_number == 1 or row_number % 100 == 0 or row_number == total_rows:
            report_progress(row_number)

    summary = {
        "rows_processed": len(rows),
        "projects_created": sorted(set(projects_created)),
        "samples_created": sorted(set(samples_created)),
        "samples_matched": sorted(set(samples_matched)),
        "external_ids_created": len(external_ids_created),
        "custom_values_created": custom_values_created,
        "results_created": results_created,
        "skipped_rows": skipped_rows,
        "row_records_created": row_records_created,
        "unmapped_rows_preserved": unmapped_rows_preserved,
        "source_system": profile.source_system,
        "progress": {
            "processed_rows": total_rows,
            "total_rows": total_rows,
            "percent": 100,
        },
    }

    Event.objects.create(
        entity_type="MigrationProfile",
        entity_id=str(profile.id),
        action="MIGRATION_IMPORTED",
        actor=actor,
        payload=summary,
    )

    return summary
