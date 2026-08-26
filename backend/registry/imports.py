import hashlib
import json
import re

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from migration_toolkit.database_sources import fetch_dataset_rows
from migration_toolkit.models import (
    MigrationDataset,
    MigrationFieldMapping,
    MigrationJob,
    MigrationRowRecord,
)
from migration_toolkit.services import normalize_value, read_csv
from projects.models import Project
from sequences.models import Sequence
from sequences.molecular import sequence_checksum, validate_alphabet
from sequences.services import create_sequence_revision

from .models import RegistryAlias, RegistryRecord, RegistrySchema
from .services import create_record_version, generate_registry_id, validate_schema_data


REGISTRY_TARGETS = {
    MigrationFieldMapping.TARGET_REGISTRY_ID,
    MigrationFieldMapping.TARGET_REGISTRY_SCHEMA,
    MigrationFieldMapping.TARGET_REGISTRY_NAME,
    MigrationFieldMapping.TARGET_REGISTRY_DESCRIPTION,
    MigrationFieldMapping.TARGET_REGISTRY_CATALOG_NUMBER,
    MigrationFieldMapping.TARGET_REGISTRY_ALIAS,
    MigrationFieldMapping.TARGET_REGISTRY_TAGS,
    MigrationFieldMapping.TARGET_REGISTRY_STATUS,
    MigrationFieldMapping.TARGET_REGISTRY_DATA,
    MigrationFieldMapping.TARGET_REGISTRY_SEQUENCE,
}


def is_registry_profile(profile):
    return (
        profile.datasets.filter(entity_type=MigrationDataset.ENTITY_REGISTRY, active=True).exists()
        or profile.field_mappings.filter(target_type__in=REGISTRY_TARGETS).exists()
    )


def _group_mappings(mappings):
    grouped = {}
    for mapping in mappings:
        grouped.setdefault(mapping.target_type, []).append(mapping)
    return grouped


def _first(row, grouped, target):
    for mapping in grouped.get(target, []):
        value = row.get(mapping.source_column)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _registry_data(row, grouped):
    data = {}
    for mapping in grouped.get(MigrationFieldMapping.TARGET_REGISTRY_DATA, []):
        value = row.get(mapping.source_column)
        if value in (None, ""):
            continue
        key = mapping.target_field or mapping.source_column
        data[key] = normalize_value(value, mapping.value_type)
    return data


def _configuration(profile, payloads, conflict_policy, default_project):
    return {
        "profile": profile.id,
        "source_type": profile.source_type,
        "conflict_policy": conflict_policy,
        "default_project": default_project.id if default_project else None,
        "datasets": [
            {
                "id": payload["dataset"].id if payload["dataset"] else None,
                "mappings": [
                    {
                        "source": mapping.source_column,
                        "target": mapping.target_type,
                        "field": mapping.target_field,
                        "type": mapping.value_type,
                        "required": mapping.required,
                    }
                    for mapping in payload["mappings"]
                ],
            }
            for payload in payloads
        ],
    }


def _source_payloads(profile, uploaded_file=None):
    if profile.source_type == profile.SOURCE_TYPE_DATABASE:
        datasets = list(
            profile.datasets.filter(active=True, entity_type=MigrationDataset.ENTITY_REGISTRY)
            .select_related("connection")
            .prefetch_related("field_mappings")
        )
        if not datasets:
            raise ValueError("Add an active REGISTRY database dataset.")
        payloads = []
        for dataset in datasets:
            mappings = list(dataset.field_mappings.all().order_by("id"))
            columns = sorted({dataset.source_key_column, *(item.source_column for item in mappings)})
            payloads.append({
                "dataset": dataset,
                "mappings": mappings,
                "rows": fetch_dataset_rows(dataset, columns),
            })
        return payloads
    if uploaded_file is None:
        raise ValueError("A CSV file is required.")
    rows, _fieldnames = read_csv(uploaded_file)
    return [{
        "dataset": None,
        "mappings": list(profile.field_mappings.filter(dataset__isnull=True).order_by("id")),
        "rows": rows,
    }]


def _fingerprint(payloads, configuration):
    source = [
        {
            "dataset": payload["dataset"].id if payload["dataset"] else None,
            "rows": payload["rows"],
        }
        for payload in payloads
    ]
    encoded = json.dumps(
        {"configuration": configuration, "source": source},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _row_values(row, grouped, default_project=None):
    schema_code = _first(row, grouped, MigrationFieldMapping.TARGET_REGISTRY_SCHEMA)
    schema = (
        RegistrySchema.objects.filter(active=True, code__iexact=schema_code).order_by("-version").first()
        or RegistrySchema.objects.filter(active=True, entity_type__iexact=schema_code).order_by("-version").first()
    )
    project_code = _first(row, grouped, MigrationFieldMapping.TARGET_PROJECT_CODE)
    project = Project.objects.filter(code__iexact=project_code).first() if project_code else default_project
    data = _registry_data(row, grouped)
    sequence = _first(row, grouped, MigrationFieldMapping.TARGET_REGISTRY_SEQUENCE)
    sequence_type = str(data.get("sequence_type") or (
        "RNA" if schema and schema.entity_type.lower() == "rna" else
        "PROTEIN" if schema and schema.entity_type.lower() == "protein" else "DNA"
    )).upper()
    aliases = [
        str(row.get(mapping.source_column)).strip()
        for mapping in grouped.get(MigrationFieldMapping.TARGET_REGISTRY_ALIAS, [])
        if row.get(mapping.source_column) not in (None, "")
    ]
    external_ids = {
        mapping.target_field or mapping.source_column: str(row.get(mapping.source_column)).strip()
        for mapping in grouped.get(MigrationFieldMapping.TARGET_EXTERNAL_ID, [])
        if row.get(mapping.source_column) not in (None, "")
    }
    tags_raw = _first(row, grouped, MigrationFieldMapping.TARGET_REGISTRY_TAGS)
    tags = [item.strip() for item in re.split(r"[,;|]", tags_raw) if item.strip()]
    return {
        "schema": schema,
        "schema_code": schema_code,
        "registry_id": _first(row, grouped, MigrationFieldMapping.TARGET_REGISTRY_ID),
        "name": _first(row, grouped, MigrationFieldMapping.TARGET_REGISTRY_NAME),
        "description": _first(row, grouped, MigrationFieldMapping.TARGET_REGISTRY_DESCRIPTION),
        "catalog_number": _first(row, grouped, MigrationFieldMapping.TARGET_REGISTRY_CATALOG_NUMBER),
        "status": _first(row, grouped, MigrationFieldMapping.TARGET_REGISTRY_STATUS).upper() or RegistryRecord.STATUS_DRAFT,
        "project": project,
        "project_code": project_code,
        "data": data,
        "sequence": sequence,
        "sequence_type": sequence_type,
        "aliases": aliases,
        "external_identifiers": external_ids,
        "tags": tags,
    }


def prepare_registry_preview(profile, *, uploaded_file=None, default_project=None, conflict_policy=MigrationJob.CONFLICT_SKIP):
    payloads = _source_payloads(profile, uploaded_file)
    configuration = _configuration(profile, payloads, conflict_policy, default_project)
    fingerprint = _fingerprint(payloads, configuration)
    preview_rows = []
    errors = []
    duplicates = 0
    total = 0
    for payload in payloads:
        grouped = _group_mappings(payload["mappings"])
        required_targets = {MigrationFieldMapping.TARGET_REGISTRY_SCHEMA, MigrationFieldMapping.TARGET_REGISTRY_NAME}
        missing_targets = required_targets - set(grouped)
        if missing_targets:
            errors.append({"row": None, "errors": [f"Missing mapping {target}." for target in sorted(missing_targets)]})
        for row_number, row in enumerate(payload["rows"], 1):
            total += 1
            row_errors = []
            for mappings in grouped.values():
                for mapping in mappings:
                    if mapping.required and row.get(mapping.source_column) in (None, ""):
                        row_errors.append(f"Required column {mapping.source_column} is empty.")
            values = _row_values(row, grouped, default_project)
            if not values["schema"]:
                row_errors.append(f"Registry schema {values['schema_code'] or '-'} was not found.")
            if not values["name"]:
                row_errors.append("Registry name is required.")
            if values["project_code"] and not values["project"]:
                row_errors.append(f"Project {values['project_code']} was not found.")
            if values["status"] not in dict(RegistryRecord.STATUS_CHOICES):
                row_errors.append(f"Unknown lifecycle status {values['status']}.")
            checksum = ""
            if values["sequence"]:
                try:
                    cleaned = validate_alphabet(values["sequence"], values["sequence_type"])
                    checksum = sequence_checksum(cleaned, values["sequence_type"])
                except ValueError as exc:
                    row_errors.append(str(exc))
            try:
                if values["schema"]:
                    validate_schema_data(values["schema"].schema, values["data"])
            except ValueError as exc:
                row_errors.append(str(exc.args[0] if exc.args else exc))
            duplicate_query = Q()
            if values["registry_id"]:
                duplicate_query |= Q(registry_id__iexact=values["registry_id"])
            if values["catalog_number"]:
                duplicate_query |= Q(catalog_number__iexact=values["catalog_number"])
            if checksum:
                duplicate_query |= Q(current_version__sequence_checksum=checksum)
            existing = RegistryRecord.objects.filter(duplicate_query).first() if duplicate_query else None
            if not existing and values["aliases"]:
                existing_alias = RegistryAlias.objects.filter(alias__in=values["aliases"]).select_related("record").first()
                existing = existing_alias.record if existing_alias else None
            if existing:
                duplicates += 1
            item = {
                "dataset": payload["dataset"].name if payload["dataset"] else "CSV",
                "row": row_number,
                "registry_id": values["registry_id"],
                "name": values["name"],
                "schema": values["schema_code"],
                "project": values["project_code"] or (default_project.code if default_project else None),
                "existing_registry_id": existing.registry_id if existing else None,
                "action": "CREATE" if not existing else conflict_policy,
                "errors": row_errors,
            }
            preview_rows.append(item)
            if row_errors:
                errors.append(item)
    summary = {
        "module": "REGISTRY",
        "source_type": profile.source_type,
        "rows_processed": total,
        "duplicates": duplicates,
        "records_to_create": total - duplicates - len([item for item in preview_rows if item["errors"]]),
        "validation_error_count": sum(len(item["errors"]) for item in errors),
        "errors": errors[:100],
        "preview_rows": preview_rows[:100],
        "conflict_policy": conflict_policy,
        "ready_to_commit": not errors,
        "preview_fingerprint": fingerprint,
        "source_snapshot": {"fingerprint": fingerprint, "datasets": len(payloads), "rows": total},
    }
    return summary, payloads


@transaction.atomic
def apply_registry_migration(job, actor):
    uploaded_file = None
    if job.profile.source_type == job.profile.SOURCE_TYPE_CSV:
        job.uploaded_file.open("rb")
        uploaded_file = job.uploaded_file
    summary, payloads = prepare_registry_preview(
        job.profile,
        uploaded_file=uploaded_file,
        default_project=job.project,
        conflict_policy=job.conflict_policy,
    )
    if summary["preview_fingerprint"] != job.preview_fingerprint:
        raise ValueError("The registry source or mappings changed after preview.")
    if not summary["ready_to_commit"]:
        raise ValueError("Registry migration has validation errors.")
    created = updated = skipped = 0
    for payload in payloads:
        grouped = _group_mappings(payload["mappings"])
        dataset = payload["dataset"]
        for row_number, row in enumerate(payload["rows"], 1):
            values = _row_values(row, grouped, job.project)
            checksum = ""
            if values["sequence"]:
                checksum = sequence_checksum(values["sequence"], values["sequence_type"])
            duplicate_query = Q()
            if values["registry_id"]:
                duplicate_query |= Q(registry_id__iexact=values["registry_id"])
            if values["catalog_number"]:
                duplicate_query |= Q(catalog_number__iexact=values["catalog_number"])
            if checksum:
                duplicate_query |= Q(current_version__sequence_checksum=checksum)
            record = RegistryRecord.objects.filter(duplicate_query).first() if duplicate_query else None
            if not record and values["aliases"]:
                match = RegistryAlias.objects.filter(alias__in=values["aliases"]).select_related("record").first()
                record = match.record if match else None
            action = MigrationRowRecord.ACTION_CREATE
            if record and job.conflict_policy == MigrationJob.CONFLICT_SKIP:
                skipped += 1
                MigrationRowRecord.objects.create(
                    migration_job=job, source_dataset=dataset, row_number=row_number,
                    entity_type=MigrationDataset.ENTITY_REGISTRY,
                    source_key=values["registry_id"] or values["name"], raw_row=row,
                    status=MigrationRowRecord.STATUS_SKIPPED, action=MigrationRowRecord.ACTION_SKIP,
                    target_object_type="REGISTRY_RECORD", target_object_id=str(record.public_id),
                )
                continue
            if record and job.conflict_policy == MigrationJob.CONFLICT_CREATE_NEW:
                record = None
                action = MigrationRowRecord.ACTION_CREATE_NEW
            if record:
                action = (
                    MigrationRowRecord.ACTION_MERGE
                    if job.conflict_policy == MigrationJob.CONFLICT_MERGE
                    else MigrationRowRecord.ACTION_OVERWRITE
                )
                if job.conflict_policy == MigrationJob.CONFLICT_OVERWRITE:
                    record.name = values["name"]
                    record.description = values["description"]
                    record.catalog_number = values["catalog_number"]
                    record.external_identifiers = values["external_identifiers"]
                    record.tags = values["tags"]
                else:
                    record.description = record.description or values["description"]
                    record.catalog_number = record.catalog_number or values["catalog_number"]
                    record.external_identifiers = {**values["external_identifiers"], **record.external_identifiers}
                    record.tags = list(dict.fromkeys([*record.tags, *values["tags"]]))
                record.save()
                updated += 1
            else:
                record = RegistryRecord.objects.create(
                    registry_id=values["registry_id"] or generate_registry_id(values["schema"]),
                    schema=values["schema"], name=values["name"], description=values["description"],
                    catalog_number=values["catalog_number"], external_identifiers=values["external_identifiers"],
                    tags=values["tags"], project=values["project"], owner=actor,
                    visibility=RegistryRecord.VISIBILITY_PROJECT if values["project"] else RegistryRecord.VISIBILITY_PRIVATE,
                )
                created += 1
            revision = None
            if values["sequence"]:
                sequence_record = Sequence.objects.create(
                    name=f"{record.registry_id} sequence", sequence_type=values["sequence_type"],
                    sequence=validate_alphabet(values["sequence"], values["sequence_type"]),
                    topology="CIRCULAR" if values["schema"].entity_type.lower() in {"plasmid", "vector", "construct"} else "LINEAR",
                    project=values["project"], created_by=actor, source_type="MANUAL",
                    source_metadata={"migration_job": job.id, "source_system": job.profile.source_system},
                )
                revision = create_sequence_revision(
                    sequence_record, actor=actor, change_summary=f"Imported from {job.profile.source_system}",
                    registry_record=record,
                )
            create_record_version(
                record, data=values["data"], actor=actor, schema=values["schema"],
                sequence_revision=revision, change_summary=f"Imported from {job.profile.source_system}",
                audit_action="REGISTRY_RECORD_IMPORTED",
            )
            record.lifecycle_status = values["status"]
            if values["status"] == RegistryRecord.STATUS_REGISTERED:
                record.registered_at = timezone.now()
            elif values["status"] == RegistryRecord.STATUS_RETIRED:
                record.retired_at = timezone.now()
            record.save(update_fields=["lifecycle_status", "registered_at", "retired_at", "updated_at"])
            for alias in values["aliases"]:
                RegistryAlias.objects.get_or_create(record=record, alias=alias)
            MigrationRowRecord.objects.create(
                migration_job=job, source_dataset=dataset, row_number=row_number,
                entity_type=MigrationDataset.ENTITY_REGISTRY,
                source_key=values["registry_id"] or values["name"], project=values["project"],
                project_code=values["project_code"], raw_row=row,
                status=MigrationRowRecord.STATUS_IMPORTED, action=action,
                target_object_type="REGISTRY_RECORD", target_object_id=str(record.public_id),
            )
    return {
        **summary,
        "records_created": created,
        "records_updated": updated,
        "records_skipped": skipped,
        "finished_at": timezone.now().isoformat(),
    }
