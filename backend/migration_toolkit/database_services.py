import hashlib
import json
from datetime import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from events.models import Event
from projects.models import Project
from results.models import Result, WorkItem
from samples.models import Sample

from .database_sources import fetch_dataset_rows, rows_fingerprint
from .change_services import (
    action_for_conflict,
    record_created,
    record_updated,
    unique_value,
)
from .models import (
    MigrationDataset,
    MigrationFieldMapping,
    MigrationJob,
    MigrationProfile,
    MigrationRowRecord,
    SampleExternalID,
)
from .services import create_sample_custom_field_value, normalize_bool, normalize_value


User = get_user_model()

ENTITY_ORDER = {
    MigrationDataset.ENTITY_USER: 0,
    MigrationDataset.ENTITY_PROJECT: 1,
    MigrationDataset.ENTITY_SAMPLE: 2,
    MigrationDataset.ENTITY_RESULT: 3,
}

REQUIRED_TARGETS = {
    MigrationDataset.ENTITY_USER: [MigrationFieldMapping.TARGET_USER_USERNAME],
    MigrationDataset.ENTITY_PROJECT: [MigrationFieldMapping.TARGET_PROJECT_CODE],
    MigrationDataset.ENTITY_SAMPLE: [
        MigrationFieldMapping.TARGET_SAMPLE_ID,
        MigrationFieldMapping.TARGET_PROJECT_CODE,
    ],
    MigrationDataset.ENTITY_RESULT: [
        MigrationFieldMapping.TARGET_SAMPLE_ID,
        MigrationFieldMapping.TARGET_RESULT_VALUE,
    ],
}


def _group_mappings(dataset):
    grouped = {}
    for mapping in dataset.field_mappings.all().order_by("id"):
        grouped.setdefault(mapping.target_type, []).append(mapping)
    return grouped


def _first(row, mappings, target_type):
    for mapping in mappings.get(target_type, []):
        value = row.get(mapping.source_column)
        if value not in [None, ""]:
            return str(value).strip(), mapping
    return None, None


def _parse_timestamp(value):
    if value in [None, ""]:
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid timestamp: {value}") from exc
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _mapping_configuration(profile, datasets):
    return {
        "profile_id": profile.id,
        "source_system": profile.source_system,
        "datasets": [
            {
                "id": dataset.id,
                "connection_id": dataset.connection_id,
                "connection": {
                    "engine": dataset.connection.engine,
                    "host": dataset.connection.host,
                    "port": dataset.connection.port,
                    "database_name": dataset.connection.database_name,
                    "username": dataset.connection.username,
                    "password_env_var": dataset.connection.password_env_var,
                    "ssl_mode": dataset.connection.ssl_mode,
                },
                "entity_type": dataset.entity_type,
                "schema": dataset.source_schema,
                "table": dataset.source_table,
                "key": dataset.source_key_column,
                "row_limit": dataset.row_limit,
                "mappings": [
                    {
                        "source": mapping.source_column,
                        "target": mapping.target_type,
                        "field": mapping.target_field,
                        "value_type": mapping.value_type,
                        "required": mapping.required,
                    }
                    for mapping in dataset.field_mappings.all().order_by("id")
                ],
            }
            for dataset in datasets
        ],
    }


def _fingerprint(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_mapping_configuration(dataset, mappings):
    errors = []
    configured_targets = set(mappings)
    for target in REQUIRED_TARGETS[dataset.entity_type]:
        if target not in configured_targets:
            errors.append(f"Dataset {dataset.name} needs a {target} mapping.")

    if dataset.entity_type == MigrationDataset.ENTITY_RESULT:
        value_mappings = mappings.get(MigrationFieldMapping.TARGET_RESULT_VALUE, [])
        has_row_key = MigrationFieldMapping.TARGET_RESULT_KEY in configured_targets
        if any(not mapping.target_field for mapping in value_mappings) and not has_row_key:
            errors.append(
                f"Dataset {dataset.name} needs RESULT_KEY when a result value has no fixed target field."
            )
    return errors


def _validate_row_types(row, mappings):
    errors = []
    for mapping_list in mappings.values():
        for mapping in mapping_list:
            raw_value = row.get(mapping.source_column)
            if mapping.required and raw_value in [None, ""]:
                errors.append(f"Required column {mapping.source_column} is empty.")
                continue
            if raw_value in [None, ""]:
                continue
            try:
                normalized = normalize_value(raw_value, mapping.value_type)
                if (
                    mapping.value_type == MigrationFieldMapping.VALUE_TYPE_BOOLEAN
                    and normalized is None
                ):
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(
                    f"{mapping.source_column} cannot be converted to {mapping.value_type}."
                )

    timestamp_targets = [
        MigrationFieldMapping.TARGET_SAMPLE_CREATED_AT,
        MigrationFieldMapping.TARGET_WORK_ITEM_CREATED_AT,
        MigrationFieldMapping.TARGET_RESULT_CREATED_AT,
    ]
    for target in timestamp_targets:
        value, _ = _first(row, mappings, target)
        if value:
            try:
                _parse_timestamp(value)
            except ValueError as exc:
                errors.append(str(exc))
    return errors


def prepare_database_preview(
    profile,
    preview_limit=100,
    include_rows=False,
    conflict_policy=MigrationJob.CONFLICT_SKIP,
):
    if profile.source_type != MigrationProfile.SOURCE_TYPE_DATABASE:
        raise ValidationError("This profile is not configured for a database source.")

    datasets = list(
        profile.datasets.filter(active=True)
        .select_related("connection")
        .prefetch_related("field_mappings")
    )
    datasets.sort(key=lambda item: (ENTITY_ORDER[item.entity_type], item.id))
    if not datasets:
        raise ValidationError("Add at least one active database dataset before previewing.")

    configuration = {
        **_mapping_configuration(profile, datasets),
        "conflict_policy": conflict_policy,
    }
    mapping_fingerprint = _fingerprint(configuration)
    payloads = []
    snapshots = []
    validation_errors = []
    validation_warnings = []

    for dataset in datasets:
        mappings = _group_mappings(dataset)
        config_errors = _validate_mapping_configuration(dataset, mappings)
        validation_errors.extend(
            {"dataset": dataset.name, "row": None, "message": message}
            for message in config_errors
        )
        columns = [
            mapping.source_column
            for mapping_list in mappings.values()
            for mapping in mapping_list
        ]
        rows = fetch_dataset_rows(dataset, columns)
        row_hash = rows_fingerprint(rows)
        snapshots.append(
            {
                "dataset_id": dataset.id,
                "dataset": dataset.name,
                "entity_type": dataset.entity_type,
                "rows": len(rows),
                "fingerprint": row_hash,
            }
        )
        payloads.append({"dataset": dataset, "mappings": mappings, "rows": rows})

    planned_projects = set(Project.objects.values_list("code", flat=True))
    planned_users = set(User.objects.values_list("username", flat=True))
    planned_samples = set(Sample.objects.values_list("sample_id", flat=True))
    create_new_sample_identifiers = set()

    for payload in payloads:
        mappings = payload["mappings"]
        for row in payload["rows"]:
            if payload["dataset"].entity_type == MigrationDataset.ENTITY_PROJECT:
                value, _ = _first(row, mappings, MigrationFieldMapping.TARGET_PROJECT_CODE)
                if value:
                    planned_projects.add(value)
            elif payload["dataset"].entity_type == MigrationDataset.ENTITY_USER:
                value, _ = _first(row, mappings, MigrationFieldMapping.TARGET_USER_USERNAME)
                if value:
                    planned_users.add(value)
            elif payload["dataset"].entity_type == MigrationDataset.ENTITY_SAMPLE:
                value, _ = _first(row, mappings, MigrationFieldMapping.TARGET_SAMPLE_ID)
                if value:
                    planned_samples.add(value)
                    if (
                        conflict_policy == MigrationJob.CONFLICT_CREATE_NEW
                        and Sample.objects.filter(sample_id=value).exists()
                    ):
                        create_new_sample_identifiers.add(value)

    counts = {
        entity: {
            "rows": 0,
            "to_create": 0,
            "matched": 0,
            "conflicts": 0,
            "to_skip": 0,
            "to_merge": 0,
            "to_overwrite": 0,
            "to_create_new": 0,
        }
        for entity in ENTITY_ORDER
    }
    preview_rows = []

    for payload in payloads:
        dataset = payload["dataset"]
        mappings = payload["mappings"]
        seen_keys = set()
        seen_identifiers = set()
        for row_number, row in enumerate(payload["rows"], start=1):
            row_errors = _validate_row_types(row, mappings)
            row_warnings = []
            source_key = str(row.get(dataset.source_key_column, "")).strip()
            if not source_key:
                row_errors.append(f"Source key {dataset.source_key_column} is empty.")
            elif source_key in seen_keys:
                row_errors.append(f"Duplicate source key {source_key}.")
            seen_keys.add(source_key)

            identifier = ""
            exists = False
            if dataset.entity_type == MigrationDataset.ENTITY_USER:
                identifier, _ = _first(row, mappings, MigrationFieldMapping.TARGET_USER_USERNAME)
                if not identifier:
                    row_errors.append("Missing user username.")
                exists = bool(identifier and User.objects.filter(username=identifier).exists())
                role, _ = _first(row, mappings, MigrationFieldMapping.TARGET_USER_ROLE)
                if role and role.lower() not in ["viewer", "tech"]:
                    row_warnings.append(
                        f"Role {role} will be replaced with viewer; privileged roles are never imported."
                    )
            elif dataset.entity_type == MigrationDataset.ENTITY_PROJECT:
                identifier, _ = _first(row, mappings, MigrationFieldMapping.TARGET_PROJECT_CODE)
                name, _ = _first(row, mappings, MigrationFieldMapping.TARGET_PROJECT_NAME)
                if not identifier:
                    row_errors.append("Missing project code.")
                if not name:
                    row_errors.append("Missing project name.")
                elif (
                    conflict_policy != MigrationJob.CONFLICT_CREATE_NEW
                    and Project.objects.filter(name=name).exclude(code=identifier).exists()
                ):
                    row_errors.append(f"Project name {name} already belongs to another code.")
                exists = bool(identifier and Project.objects.filter(code=identifier).exists())
            elif dataset.entity_type == MigrationDataset.ENTITY_SAMPLE:
                identifier, _ = _first(row, mappings, MigrationFieldMapping.TARGET_SAMPLE_ID)
                project_code, _ = _first(row, mappings, MigrationFieldMapping.TARGET_PROJECT_CODE)
                if not identifier:
                    row_errors.append("Missing sample ID.")
                if not project_code or project_code not in planned_projects:
                    row_errors.append(f"Project {project_code or '-'} is not available for this sample.")
                exists = bool(identifier and Sample.objects.filter(sample_id=identifier).exists())
                status_value, _ = _first(row, mappings, MigrationFieldMapping.TARGET_SAMPLE_STATUS)
                if status_value and status_value.upper() not in dict(Sample.STATUS_CHOICES):
                    row_errors.append(f"Unknown sample status {status_value}.")
            else:
                identifier, _ = _first(row, mappings, MigrationFieldMapping.TARGET_SAMPLE_ID)
                if not identifier or identifier not in planned_samples:
                    row_errors.append(f"Sample {identifier or '-'} is not available for this result.")
                result_key, _ = _first(row, mappings, MigrationFieldMapping.TARGET_RESULT_KEY)
                value_mappings = mappings.get(MigrationFieldMapping.TARGET_RESULT_VALUE, [])
                if not value_mappings:
                    row_errors.append("Missing result value mapping.")
                for mapping in value_mappings:
                    if row.get(mapping.source_column) not in [None, ""] and not (
                        mapping.target_field or result_key
                    ):
                        row_errors.append("A result key is required for every value.")
                work_status, _ = _first(
                    row, mappings, MigrationFieldMapping.TARGET_WORK_ITEM_STATUS
                )
                if work_status and work_status.upper() not in dict(WorkItem.STATUS_CHOICES):
                    row_errors.append(f"Unknown work item status {work_status}.")
                qc_status, _ = _first(
                    row, mappings, MigrationFieldMapping.TARGET_RESULT_QC_STATUS
                )
                if qc_status and qc_status.upper() not in dict(Result.QC_STATUS_CHOICES):
                    row_errors.append(f"Unknown result QC status {qc_status}.")
                entered_by, _ = _first(
                    row, mappings, MigrationFieldMapping.TARGET_RESULT_ENTERED_BY
                )
                if entered_by and entered_by not in planned_users:
                    row_errors.append(f"Result user {entered_by} is not available.")
                for target in [
                    MigrationFieldMapping.TARGET_RESULT_REFERENCE_MIN,
                    MigrationFieldMapping.TARGET_RESULT_REFERENCE_MAX,
                ]:
                    reference, _ = _first(row, mappings, target)
                    if reference:
                        try:
                            float(reference)
                        except (TypeError, ValueError):
                            row_errors.append(f"Reference value {reference} is not numeric.")
                work_name, _ = _first(
                    row, mappings, MigrationFieldMapping.TARGET_WORK_ITEM_NAME
                )
                work_name = work_name or "Migrated Results"
                result_keys = [
                    mapping.target_field or result_key
                    for mapping in value_mappings
                    if row.get(mapping.source_column) not in [None, ""]
                    and (mapping.target_field or result_key)
                ]
                exists = bool(
                    identifier
                    and identifier not in create_new_sample_identifiers
                    and result_keys
                    and Result.objects.filter(
                        work_item__sample__sample_id=identifier,
                        work_item__name=work_name,
                        key__in=result_keys,
                    ).exists()
                )

            if dataset.entity_type != MigrationDataset.ENTITY_RESULT and identifier:
                if identifier.lower() in seen_identifiers:
                    row_errors.append(f"Duplicate target identifier {identifier}.")
                seen_identifiers.add(identifier.lower())

            counts[dataset.entity_type]["rows"] += 1
            if exists:
                counts[dataset.entity_type]["matched"] += 1
                counts[dataset.entity_type]["conflicts"] += 1
                counts[dataset.entity_type][{
                    MigrationJob.CONFLICT_SKIP: "to_skip",
                    MigrationJob.CONFLICT_MERGE: "to_merge",
                    MigrationJob.CONFLICT_OVERWRITE: "to_overwrite",
                    MigrationJob.CONFLICT_CREATE_NEW: "to_create_new",
                }[conflict_policy]] += 1
            else:
                counts[dataset.entity_type]["to_create"] += 1

            for message in row_errors:
                validation_errors.append(
                    {"dataset": dataset.name, "row": row_number, "message": message}
                )
            for message in row_warnings:
                validation_warnings.append(
                    {"dataset": dataset.name, "row": row_number, "message": message}
                )
            if len(preview_rows) < preview_limit:
                preview_rows.append(
                    {
                        "row": row_number,
                        "dataset_id": dataset.id,
                        "dataset": dataset.name,
                        "entity_type": dataset.entity_type,
                        "source_key": source_key,
                        "identifier": identifier,
                        "action": (
                            action_for_conflict(conflict_policy)
                            if exists
                            else MigrationRowRecord.ACTION_CREATE
                        ),
                        "will_skip": bool(row_errors),
                        "errors": row_errors,
                        "warnings": row_warnings,
                    }
                )

    source_snapshot = {
        "mapping_fingerprint": mapping_fingerprint,
        "datasets": snapshots,
    }
    preview_fingerprint = _fingerprint(source_snapshot)
    rows_processed = sum(item["rows"] for item in snapshots)
    summary = {
        "source_type": MigrationProfile.SOURCE_TYPE_DATABASE,
        "source_system": profile.source_system,
        "conflict_policy": conflict_policy,
        "conflict_count": sum(item["conflicts"] for item in counts.values()),
        "rows_processed": rows_processed,
        "entity_counts": counts,
        "datasets": snapshots,
        "validation_errors": validation_errors[:500],
        "validation_error_count": len(validation_errors),
        "validation_warnings": validation_warnings[:500],
        "validation_warning_count": len(validation_warnings),
        "ready_to_commit": not validation_errors,
        "preview_rows": preview_rows,
        "preview_limit": preview_limit,
        "preview_rows_returned": len(preview_rows),
        "preview_fingerprint": preview_fingerprint,
    }
    return summary, source_snapshot, payloads if include_rows else None


def _set_created_at(model_class, object_id, timestamp):
    if timestamp:
        model_class.objects.filter(id=object_id).update(created_at=timestamp)


def _record_row(
    job,
    dataset,
    row_number,
    row,
    entity,
    source_key,
    project=None,
    sample=None,
    action=MigrationRowRecord.ACTION_CREATE,
    status=MigrationRowRecord.STATUS_IMPORTED,
    target_object=None,
    errors=None,
):
    MigrationRowRecord.objects.create(
        migration_job=job,
        source_dataset=dataset,
        entity_type=entity,
        source_key=source_key,
        project=project,
        sample=sample,
        row_number=row_number,
        project_code=project.code if project else "",
        project_name=project.name if project else "",
        sample_code=sample.sample_id if sample else "",
        raw_row=row,
        raw_row_text=json.dumps(row, sort_keys=True),
        status=status,
        action=action,
        target_object_type=entity if target_object else "",
        target_object_id=str(target_object.pk) if target_object else "",
        errors=errors or [],
    )


def _safe_role(value):
    value = str(value or "").strip().lower()
    return value if value in ["viewer", "tech"] else "viewer"


def _apply_values(job, instance, object_type, values, policy, identifier="", metadata=None):
    changes = {}
    for field, value in values.items():
        if value is None:
            continue
        current = getattr(instance, field)
        if policy == MigrationJob.CONFLICT_MERGE:
            if current in [None, ""] and value not in [None, ""]:
                changes[field] = value
        elif policy == MigrationJob.CONFLICT_OVERWRITE and current != value:
            changes[field] = value
    if not changes:
        return False
    record_updated(
        job,
        instance,
        object_type,
        list(changes),
        identifier,
        metadata=metadata,
    )
    for field, value in changes.items():
        setattr(instance, field, value)
    instance.save(
        update_fields=[field[:-3] if field.endswith("_id") else field for field in changes]
    )
    return True


@transaction.atomic
def apply_database_migration(job, actor):
    summary, source_snapshot, payloads = prepare_database_preview(
        job.profile,
        include_rows=True,
        conflict_policy=job.conflict_policy,
    )
    if not job.preview_fingerprint or summary["preview_fingerprint"] != job.preview_fingerprint:
        raise ValidationError(
            "The source database or field mappings changed after preview. Preview again before committing."
        )
    if not summary["ready_to_commit"]:
        raise ValidationError("Migration validation failed. Correct the mappings and preview again.")

    imported = {
        "users": 0,
        "projects": 0,
        "samples": 0,
        "results": 0,
        "matched": 0,
        "skipped": 0,
        "merged": 0,
        "overwritten": 0,
        "created_new": 0,
    }
    policy = job.conflict_policy
    user_targets = {}
    project_targets = {}
    sample_targets = {}
    MigrationRowRecord.objects.filter(migration_job=job).delete()
    job.object_changes.all().delete()

    for payload in payloads:
        dataset = payload["dataset"]
        mappings = payload["mappings"]
        mapped_columns = {
            mapping.source_column
            for mapping_list in mappings.values()
            for mapping in mapping_list
        }
        for row_number, row in enumerate(payload["rows"], start=1):
            source_key = str(row.get(dataset.source_key_column, "")).strip()
            project = None
            sample = None
            target_object = None
            row_action = MigrationRowRecord.ACTION_CREATE
            row_status = MigrationRowRecord.STATUS_IMPORTED
            row_errors = []

            if dataset.entity_type == MigrationDataset.ENTITY_USER:
                username, _ = _first(row, mappings, MigrationFieldMapping.TARGET_USER_USERNAME)
                user = User.objects.filter(username=username).first()
                if user:
                    imported["matched"] += 1
                    row_action = action_for_conflict(policy)
                    if policy == MigrationJob.CONFLICT_SKIP:
                        imported["skipped"] += 1
                        row_status = MigrationRowRecord.STATUS_SKIPPED
                        row_errors = ["Existing user skipped by conflict policy."]
                    elif policy == MigrationJob.CONFLICT_CREATE_NEW:
                        username = unique_value(User, "username", username, 150)
                        user = None
                        imported["created_new"] += 1
                email, _ = _first(row, mappings, MigrationFieldMapping.TARGET_USER_EMAIL)
                first_name, _ = _first(row, mappings, MigrationFieldMapping.TARGET_USER_FIRST_NAME)
                last_name, _ = _first(row, mappings, MigrationFieldMapping.TARGET_USER_LAST_NAME)
                role, _ = _first(row, mappings, MigrationFieldMapping.TARGET_USER_ROLE)
                if user is None:
                    user = User(
                        username=username,
                        email=email or "",
                        first_name=first_name or "",
                        last_name=last_name or "",
                        is_active=False,
                    )
                    user.set_unusable_password()
                    user.save()
                    group, _ = Group.objects.get_or_create(name=_safe_role(role))
                    user.groups.add(group)
                    imported["users"] += 1
                    record_created(job, user, "USER", username)
                    if row_action != MigrationRowRecord.ACTION_CREATE_NEW:
                        row_action = MigrationRowRecord.ACTION_CREATE
                elif policy in [MigrationJob.CONFLICT_MERGE, MigrationJob.CONFLICT_OVERWRITE]:
                    current_groups = list(user.groups.values_list("name", flat=True))
                    changed = _apply_values(
                        job,
                        user,
                        "USER",
                        {
                            "email": email,
                            "first_name": first_name,
                            "last_name": last_name,
                        },
                        policy,
                        username,
                        metadata={"groups": current_groups},
                    )
                    if role:
                        safe_role = _safe_role(role)
                        if safe_role not in current_groups:
                            record_updated(
                                job,
                                user,
                                "USER",
                                [],
                                username,
                                metadata={"groups": current_groups},
                            )
                            group, _ = Group.objects.get_or_create(name=safe_role)
                            user.groups.add(group)
                            changed = True
                    imported[
                        "merged" if policy == MigrationJob.CONFLICT_MERGE else "overwritten"
                    ] += int(changed)
                user_targets[str(_first(row, mappings, MigrationFieldMapping.TARGET_USER_USERNAME)[0])] = user
                target_object = user

            elif dataset.entity_type == MigrationDataset.ENTITY_PROJECT:
                code, _ = _first(row, mappings, MigrationFieldMapping.TARGET_PROJECT_CODE)
                name, _ = _first(row, mappings, MigrationFieldMapping.TARGET_PROJECT_NAME)
                description, _ = _first(
                    row, mappings, MigrationFieldMapping.TARGET_PROJECT_DESCRIPTION
                )
                project = Project.objects.filter(code=code).first()
                if project:
                    imported["matched"] += 1
                    row_action = action_for_conflict(policy)
                    if policy == MigrationJob.CONFLICT_SKIP:
                        imported["skipped"] += 1
                        row_status = MigrationRowRecord.STATUS_SKIPPED
                        row_errors = ["Existing project skipped by conflict policy."]
                    elif policy == MigrationJob.CONFLICT_CREATE_NEW:
                        code = unique_value(Project, "code", code, 64)
                        name = unique_value(Project, "name", name, 128)
                        project = None
                        imported["created_new"] += 1
                if project is None:
                    project = Project.objects.create(
                        code=code,
                        name=name,
                        description=description or f"Migrated from {job.profile.source_system}.",
                    )
                    imported["projects"] += 1
                    record_created(job, project, "PROJECT", code)
                    if row_action != MigrationRowRecord.ACTION_CREATE_NEW:
                        row_action = MigrationRowRecord.ACTION_CREATE
                elif policy in [MigrationJob.CONFLICT_MERGE, MigrationJob.CONFLICT_OVERWRITE]:
                    changed = _apply_values(
                        job,
                        project,
                        "PROJECT",
                        {"name": name, "description": description},
                        policy,
                        code,
                    )
                    imported[
                        "merged" if policy == MigrationJob.CONFLICT_MERGE else "overwritten"
                    ] += int(changed)
                original_code, _ = _first(row, mappings, MigrationFieldMapping.TARGET_PROJECT_CODE)
                project_targets[str(original_code)] = project
                target_object = project

            elif dataset.entity_type == MigrationDataset.ENTITY_SAMPLE:
                sample_id, _ = _first(row, mappings, MigrationFieldMapping.TARGET_SAMPLE_ID)
                project_code, _ = _first(row, mappings, MigrationFieldMapping.TARGET_PROJECT_CODE)
                project = project_targets.get(str(project_code)) or Project.objects.get(
                    code=project_code
                )
                sample = Sample.objects.filter(sample_id=sample_id).first()
                if sample:
                    imported["matched"] += 1
                    row_action = action_for_conflict(policy)
                    if policy == MigrationJob.CONFLICT_SKIP:
                        imported["skipped"] += 1
                        row_status = MigrationRowRecord.STATUS_SKIPPED
                        row_errors = ["Existing sample skipped by conflict policy."]
                    elif policy == MigrationJob.CONFLICT_CREATE_NEW:
                        sample_id = unique_value(Sample, "sample_id", sample_id, 64)
                        sample = None
                        imported["created_new"] += 1
                sample_type, _ = _first(row, mappings, MigrationFieldMapping.TARGET_SAMPLE_TYPE)
                sample_status, _ = _first(row, mappings, MigrationFieldMapping.TARGET_SAMPLE_STATUS)
                if sample is None:
                    sample = Sample.objects.create(
                        sample_id=sample_id,
                        sample_type=sample_type or "GENERAL",
                        status=(sample_status or Sample.STATUS_RECEIVED).upper(),
                        project=project,
                        created_by=actor,
                    )
                    created_at, _ = _first(
                        row, mappings, MigrationFieldMapping.TARGET_SAMPLE_CREATED_AT
                    )
                    _set_created_at(Sample, sample.id, _parse_timestamp(created_at))
                    imported["samples"] += 1
                    record_created(job, sample, "SAMPLE", sample_id)
                    if row_action != MigrationRowRecord.ACTION_CREATE_NEW:
                        row_action = MigrationRowRecord.ACTION_CREATE
                elif policy in [MigrationJob.CONFLICT_MERGE, MigrationJob.CONFLICT_OVERWRITE]:
                    changed = _apply_values(
                        job,
                        sample,
                        "SAMPLE",
                        {
                            "sample_type": sample_type,
                            "status": sample_status.upper() if sample_status else None,
                            "project_id": project.id,
                        },
                        policy,
                        sample_id,
                    )
                    imported[
                        "merged" if policy == MigrationJob.CONFLICT_MERGE else "overwritten"
                    ] += int(changed)

                original_sample_id, _ = _first(
                    row, mappings, MigrationFieldMapping.TARGET_SAMPLE_ID
                )
                sample_targets[str(original_sample_id)] = sample
                target_object = sample

                if row_status == MigrationRowRecord.STATUS_SKIPPED:
                    _record_row(
                        job, dataset, row_number, row, dataset.entity_type, source_key,
                        project=project, sample=sample, action=row_action, status=row_status,
                        target_object=sample, errors=row_errors,
                    )
                    continue

                for mapping in mappings.get(MigrationFieldMapping.TARGET_EXTERNAL_ID, []):
                    value = row.get(mapping.source_column)
                    if value not in [None, ""]:
                        external_value = str(value)
                        external = SampleExternalID.objects.filter(
                            source_system=job.profile.source_system,
                            external_id=external_value,
                            label=mapping.target_field or mapping.source_column,
                        ).first()
                        if external and policy == MigrationJob.CONFLICT_CREATE_NEW:
                            external_value = unique_value(
                                SampleExternalID, "external_id", external_value, 255
                            )
                            external = None
                        if external is None:
                            external = SampleExternalID.objects.create(
                                source_system=job.profile.source_system,
                                external_id=external_value,
                                label=mapping.target_field or mapping.source_column,
                                sample=sample,
                                metadata={"dataset_id": dataset.id},
                            )
                            record_created(job, external, "EXTERNAL_ID", external_value)
                        elif policy == MigrationJob.CONFLICT_OVERWRITE and external.sample_id != sample.id:
                            record_updated(
                                job, external, "EXTERNAL_ID", ["sample_id"], external_value
                            )
                            external.sample = sample
                            external.save(update_fields=["sample"])
                for mapping in mappings.get(MigrationFieldMapping.TARGET_CUSTOM_FIELD, []):
                    create_sample_custom_field_value(
                        sample,
                        mapping.target_field or mapping.source_column,
                        row.get(mapping.source_column),
                        mapping.value_type,
                        job.profile,
                        job=job,
                        conflict_policy=policy,
                    )
                for column, value in row.items():
                    if column not in mapped_columns and column != dataset.source_key_column:
                        create_sample_custom_field_value(
                            sample,
                            column,
                            value,
                            MigrationFieldMapping.VALUE_TYPE_STRING,
                            job.profile,
                            job=job,
                            conflict_policy=policy,
                        )

            else:
                sample_id, _ = _first(row, mappings, MigrationFieldMapping.TARGET_SAMPLE_ID)
                sample = sample_targets.get(str(sample_id)) or Sample.objects.select_related(
                    "project"
                ).get(sample_id=sample_id)
                project = sample.project
                work_name, _ = _first(row, mappings, MigrationFieldMapping.TARGET_WORK_ITEM_NAME)
                work_type, _ = _first(row, mappings, MigrationFieldMapping.TARGET_WORK_ITEM_TYPE)
                work_status, _ = _first(row, mappings, MigrationFieldMapping.TARGET_WORK_ITEM_STATUS)
                work_item, work_item_was_created = WorkItem.objects.get_or_create(
                    sample=sample,
                    name=work_name or "Migrated Results",
                    defaults={
                        "work_type": work_type or "MIGRATED",
                        "status": (work_status or WorkItem.STATUS_COMPLETED).upper(),
                        "notes": f"Migrated from {job.profile.source_system}.",
                        "created_by": actor,
                    },
                )
                if work_item_was_created:
                    record_created(job, work_item, "WORK_ITEM", work_item.name)
                elif policy in [MigrationJob.CONFLICT_MERGE, MigrationJob.CONFLICT_OVERWRITE]:
                    _apply_values(
                        job,
                        work_item,
                        "WORK_ITEM",
                        {
                            "work_type": work_type,
                            "status": work_status.upper() if work_status else None,
                        },
                        policy,
                        work_item.name,
                    )
                work_created_at, _ = _first(
                    row, mappings, MigrationFieldMapping.TARGET_WORK_ITEM_CREATED_AT
                )
                if work_item_was_created:
                    _set_created_at(
                        WorkItem,
                        work_item.id,
                        _parse_timestamp(work_created_at),
                    )
                row_result_key, _ = _first(row, mappings, MigrationFieldMapping.TARGET_RESULT_KEY)
                unit, _ = _first(row, mappings, MigrationFieldMapping.TARGET_RESULT_UNIT)
                qc_status, _ = _first(row, mappings, MigrationFieldMapping.TARGET_RESULT_QC_STATUS)
                entered_username, _ = _first(
                    row, mappings, MigrationFieldMapping.TARGET_RESULT_ENTERED_BY
                )
                entered_by = user_targets.get(str(entered_username)) or User.objects.filter(
                    username=entered_username
                ).first() or actor
                reference_min, _ = _first(
                    row, mappings, MigrationFieldMapping.TARGET_RESULT_REFERENCE_MIN
                )
                reference_max, _ = _first(
                    row, mappings, MigrationFieldMapping.TARGET_RESULT_REFERENCE_MAX
                )
                result_created, _ = _first(
                    row, mappings, MigrationFieldMapping.TARGET_RESULT_CREATED_AT
                )
                for mapping in mappings.get(MigrationFieldMapping.TARGET_RESULT_VALUE, []):
                    raw_value = row.get(mapping.source_column)
                    if raw_value in [None, ""]:
                        continue
                    key = mapping.target_field or row_result_key
                    value = normalize_value(raw_value, mapping.value_type)
                    defaults = {
                        "value_type": mapping.value_type,
                        "value_string": "",
                        "value_number": None,
                        "value_boolean": None,
                        "unit": unit or "",
                        "reference_min": float(reference_min) if reference_min else None,
                        "reference_max": float(reference_max) if reference_max else None,
                        "qc_status": (qc_status or Result.QC_PENDING_REVIEW).upper(),
                        "entered_by": entered_by,
                    }
                    if mapping.value_type == MigrationFieldMapping.VALUE_TYPE_NUMBER:
                        defaults["value_number"] = value
                    elif mapping.value_type == MigrationFieldMapping.VALUE_TYPE_BOOLEAN:
                        defaults["value_boolean"] = value
                    else:
                        defaults["value_string"] = str(value)
                    result = Result.objects.filter(work_item=work_item, key=key).first()
                    result_action = MigrationRowRecord.ACTION_CREATE
                    if result:
                        imported["matched"] += 1
                        result_action = action_for_conflict(policy)
                        if policy == MigrationJob.CONFLICT_SKIP:
                            imported["skipped"] += 1
                        elif policy == MigrationJob.CONFLICT_CREATE_NEW:
                            key = unique_value(Result, "key", key, 64)
                            result = None
                            imported["created_new"] += 1
                        else:
                            update_defaults = {
                                field: value
                                for field, value in defaults.items()
                                if field != "entered_by"
                            }
                            update_defaults["entered_by_id"] = (
                                entered_by.id if entered_by else None
                            )
                            changed = _apply_values(
                                job, result, "RESULT", update_defaults, policy, key
                            )
                            imported[
                                "merged" if policy == MigrationJob.CONFLICT_MERGE else "overwritten"
                            ] += int(changed)
                    if result is None:
                        result = Result.objects.create(work_item=work_item, key=key, **defaults)
                        record_created(job, result, "RESULT", key)
                        _set_created_at(Result, result.id, _parse_timestamp(result_created))
                        imported["results"] += 1
                    row_action = result_action
                    if result_action == MigrationRowRecord.ACTION_SKIP:
                        row_status = MigrationRowRecord.STATUS_SKIPPED
                        row_errors.append(f"Existing result {key} skipped by conflict policy.")
                target_object = sample

            _record_row(
                job,
                dataset,
                row_number,
                row,
                dataset.entity_type,
                source_key,
                project=project,
                sample=sample,
                action=row_action,
                status=row_status,
                target_object=target_object,
                errors=row_errors,
            )

    final_summary = {
        **summary,
        "ready_to_commit": True,
        "users_created": imported["users"],
        "projects_created": imported["projects"],
        "samples_created": imported["samples"],
        "results_created": imported["results"],
        "records_matched": imported["matched"],
        "records_skipped": imported["skipped"],
        "records_merged": imported["merged"],
        "records_overwritten": imported["overwritten"],
        "records_created_new": imported["created_new"],
        "row_records_created": sum(len(payload["rows"]) for payload in payloads),
        "source_snapshot": source_snapshot,
        "progress": {
            "processed_rows": summary["rows_processed"],
            "total_rows": summary["rows_processed"],
            "percent": 100,
        },
    }
    Event.objects.create(
        entity_type="MigrationProfile",
        entity_id=str(job.profile_id),
        action="DATABASE_MIGRATION_IMPORTED",
        actor=actor,
        payload={key: value for key, value in final_summary.items() if key != "preview_rows"},
    )
    return final_summary
