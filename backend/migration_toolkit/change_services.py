from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from custom_fields.models import FieldDefinition, FieldValue
from events.models import Event
from projects.models import Project
from results.models import Result, WorkItem
from samples.models import Sample

from .models import (
    MigrationJob,
    MigrationObjectChange,
    MigrationRowRecord,
    SampleExternalID,
)


User = get_user_model()

OBJECT_MODELS = {
    "USER": User,
    "PROJECT": Project,
    "SAMPLE": Sample,
    "WORK_ITEM": WorkItem,
    "RESULT": Result,
    "EXTERNAL_ID": SampleExternalID,
    "FIELD_DEFINITION": FieldDefinition,
    "FIELD_VALUE": FieldValue,
}

DELETE_ORDER = [
    "RESULT",
    "FIELD_VALUE",
    "EXTERNAL_ID",
    "WORK_ITEM",
    "SAMPLE",
    "PROJECT",
    "USER",
    "FIELD_DEFINITION",
]


def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def record_created(job, instance, object_type, identifier="", metadata=None):
    if not job:
        return None
    change, _ = MigrationObjectChange.objects.get_or_create(
        migration_job=job,
        object_type=object_type,
        object_id=str(instance.pk),
        action=MigrationObjectChange.ACTION_CREATED,
        defaults={
            "identifier": str(identifier or instance),
            "metadata": metadata or {},
        },
    )
    return change


def record_updated(job, instance, object_type, fields, identifier="", metadata=None):
    if not job:
        return None
    if MigrationObjectChange.objects.filter(
        migration_job=job,
        object_type=object_type,
        object_id=str(instance.pk),
        action=MigrationObjectChange.ACTION_CREATED,
    ).exists():
        return None

    previous_values = {
        field: _json_value(getattr(instance, field))
        for field in fields
    }
    change, _ = MigrationObjectChange.objects.get_or_create(
        migration_job=job,
        object_type=object_type,
        object_id=str(instance.pk),
        action=MigrationObjectChange.ACTION_UPDATED,
        defaults={
            "identifier": str(identifier or instance),
            "previous_values": previous_values,
            "metadata": metadata or {},
        },
    )
    return change


def unique_value(model, field_name, base_value, max_length):
    base = str(base_value or "migrated").strip() or "migrated"
    counter = 2
    suffix = "-MIG"
    candidate = f"{base[:max_length-len(suffix)]}{suffix}"
    lookup = {f"{field_name}__iexact": candidate}
    while model.objects.filter(**lookup).exists():
        suffix = f"-MIG-{counter}"
        candidate = f"{base[:max_length-len(suffix)]}{suffix}"
        lookup = {f"{field_name}__iexact": candidate}
        counter += 1
    return candidate[:max_length]


def action_for_conflict(policy):
    return {
        MigrationJob.CONFLICT_SKIP: MigrationRowRecord.ACTION_SKIP,
        MigrationJob.CONFLICT_MERGE: MigrationRowRecord.ACTION_MERGE,
        MigrationJob.CONFLICT_OVERWRITE: MigrationRowRecord.ACTION_OVERWRITE,
        MigrationJob.CONFLICT_CREATE_NEW: MigrationRowRecord.ACTION_CREATE_NEW,
    }[policy]


def build_reconciliation_report(job):
    rows = job.row_records.all()
    status_counts = {
        item["status"]: item["count"]
        for item in rows.values("status").annotate(count=Count("id"))
    }
    action_counts = {
        item["action"]: item["count"]
        for item in rows.values("action").annotate(count=Count("id"))
    }
    entity_rows = {}
    for item in rows.values("entity_type", "status", "action").annotate(count=Count("id")):
        entity = item["entity_type"] or "SAMPLE"
        entry = entity_rows.setdefault(entity, {"rows": 0, "statuses": {}, "actions": {}})
        entry["rows"] += item["count"]
        entry["statuses"][item["status"]] = (
            entry["statuses"].get(item["status"], 0) + item["count"]
        )
        entry["actions"][item["action"]] = (
            entry["actions"].get(item["action"], 0) + item["count"]
        )

    change_counts = {
        item["action"]: item["count"]
        for item in job.object_changes.values("action").annotate(count=Count("id"))
    }
    object_counts = {
        item["object_type"]: item["count"]
        for item in job.object_changes.values("object_type").annotate(count=Count("id"))
    }
    source_rows = job.summary.get("rows_processed", 0)
    recorded_rows = rows.count()
    return {
        "job_id": job.id,
        "status": job.status,
        "source_system": job.profile.source_system,
        "source_type": job.profile.source_type,
        "conflict_policy": job.conflict_policy,
        "source_rows": source_rows,
        "recorded_rows": recorded_rows,
        "unrecorded_rows": max(source_rows - recorded_rows, 0),
        "status_counts": status_counts,
        "action_counts": action_counts,
        "entity_counts": entity_rows,
        "change_counts": change_counts,
        "object_counts": object_counts,
        "validation_error_count": job.summary.get("validation_error_count", 0),
        "rollback": job.rollback_summary or None,
        "generated_at": timezone.now().isoformat(),
    }


def _restore_change(change):
    model = OBJECT_MODELS.get(change.object_type)
    if not model:
        raise ValidationError(f"Unsupported rollback object type {change.object_type}.")
    instance = model.objects.filter(pk=change.object_id).first()
    if not instance:
        return False
    for field, value in change.previous_values.items():
        setattr(instance, field, value)
    if change.previous_values:
        update_fields = [
            field[:-3] if field.endswith("_id") else field
            for field in change.previous_values
        ]
        instance.save(update_fields=update_fields)
    if change.object_type == "USER" and "groups" in change.metadata:
        instance.groups.set(
            instance.groups.model.objects.filter(name__in=change.metadata["groups"])
        )
    return True


def _blocking_relations(instance):
    blockers = []
    for relation in instance._meta.related_objects:
        if relation.related_model._meta.app_label == "migration_toolkit":
            continue
        accessor = relation.get_accessor_name()
        try:
            related = getattr(instance, accessor)
            exists = related.exists() if hasattr(related, "exists") else related is not None
        except relation.related_model.DoesNotExist:
            exists = False
        if exists:
            blockers.append(relation.related_model._meta.label)
    return sorted(set(blockers))


@transaction.atomic
def rollback_migration(job, actor):
    job = MigrationJob.objects.select_for_update().select_related("profile").get(pk=job.pk)
    if job.status not in [MigrationJob.STATUS_COMPLETED, MigrationJob.STATUS_PARTIAL_FAILED]:
        raise ValidationError("Only a completed migration can be rolled back.")
    if job.rolled_back_at:
        raise ValidationError("This migration has already been rolled back.")

    restored = 0
    deleted = 0
    deleted_by_type = {}

    for change in job.object_changes.filter(
        action=MigrationObjectChange.ACTION_UPDATED
    ).order_by("-id"):
        if _restore_change(change):
            restored += 1

    for object_type in DELETE_ORDER:
        changes = job.object_changes.filter(
            action=MigrationObjectChange.ACTION_CREATED,
            object_type=object_type,
        ).order_by("-id")
        model = OBJECT_MODELS[object_type]
        for change in changes:
            instance = model.objects.filter(pk=change.object_id).first()
            if not instance:
                continue
            blockers = _blocking_relations(instance)
            if blockers:
                raise ValidationError(
                    f"Rollback blocked for {object_type} {change.identifier or change.object_id}: "
                    f"related data exists ({', '.join(blockers)})."
                )
            instance.delete()
            deleted += 1
            deleted_by_type[object_type] = deleted_by_type.get(object_type, 0) + 1

    rollback_summary = {
        "deleted_objects": deleted,
        "deleted_by_type": deleted_by_type,
        "restored_objects": restored,
        "rolled_back_at": timezone.now().isoformat(),
        "rolled_back_by": actor.username,
    }
    job.status = MigrationJob.STATUS_ROLLED_BACK
    job.rolled_back_by = actor
    job.rolled_back_at = timezone.now()
    job.rollback_summary = rollback_summary
    job.save(
        update_fields=["status", "rolled_back_by", "rolled_back_at", "rollback_summary"]
    )
    Event.objects.create(
        entity_type="MigrationJob",
        entity_id=str(job.id),
        action="MIGRATION_ROLLED_BACK",
        actor=actor,
        payload=rollback_summary,
    )
    return rollback_summary
