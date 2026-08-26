import re
import uuid

from django.db import transaction
from django.db.models import Q

from core.audit import record_audit_event
from core.permissions import is_admin, is_tech
from core.project_access import get_project_access_queryset, user_can_access_project

from .models import RegistryAlias, RegistryRecord, RegistryRecordVersion


REGISTRY_ID_RE = re.compile(r"[^A-Z0-9_-]+")


def registry_records_for_user(user, *, write=False):
    queryset = RegistryRecord.objects.all()
    if not user or not user.is_authenticated:
        return queryset.none()
    if is_admin(user):
        return queryset
    if write and not is_tech(user):
        return queryset.none()

    project_records = get_project_access_queryset(
        queryset.filter(visibility=RegistryRecord.VISIBILITY_PROJECT),
        user,
        project_lookup="project",
        owner_lookup="owner",
    )
    return (
        queryset.filter(
            Q(pk__in=project_records.values("pk"))
            | Q(owner=user)
            | Q(visibility=RegistryRecord.VISIBILITY_INSTITUTION)
        )
        .distinct()
    )


def user_can_write_record(user, record):
    if is_admin(user):
        return True
    if not is_tech(user):
        return False
    if record.owner_id == user.pk:
        return True
    return bool(
        record.project_id
        and user_can_access_project(user, record.project, write=True)
    )


def validate_schema_data(schema_definition, data, *, path="data"):
    """Validate the useful JSON-Schema subset supported by Registry v1."""

    definition = schema_definition or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be an object.")
    properties = definition.get("properties", {})
    required = definition.get("required", [])
    errors = {}

    for key in required:
        if key not in data or data[key] in (None, ""):
            errors[key] = "This field is required."

    type_map = {
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    for key, value in data.items():
        field = properties.get(key)
        if not field or value is None:
            continue
        expected = type_map.get(field.get("type"))
        if expected and (isinstance(value, bool) and field.get("type") in {"number", "integer"}):
            errors[key] = f"Expected {field['type']}."
        elif expected and not isinstance(value, expected):
            errors[key] = f"Expected {field['type']}."
        elif "enum" in field and value not in field["enum"]:
            errors[key] = "Choose a configured value."

    if errors:
        raise ValueError(errors)


def generate_registry_id(schema):
    prefix = schema.id_prefix or schema.code or schema.entity_type
    prefix = REGISTRY_ID_RE.sub("-", prefix.upper()).strip("-")[:24] or "REG"
    while True:
        candidate = f"{prefix}-{uuid.uuid4().hex[:10].upper()}"
        if not RegistryRecord.objects.filter(registry_id=candidate).exists():
            return candidate


def create_record_version(
    record,
    *,
    data,
    actor,
    schema=None,
    sequence_revision=None,
    change_summary="",
    audit_action="REGISTRY_VERSION_CREATED",
):
    schema = schema or record.schema
    if sequence_revision is not None:
        from sequences.services import link_revision_to_registry

        sequence_revision = link_revision_to_registry(
            sequence_revision,
            record,
            actor=actor,
        )
    validate_schema_data(schema.schema, data)
    with transaction.atomic():
        locked = RegistryRecord.objects.select_for_update().get(pk=record.pk)
        next_version = (
            locked.versions.order_by("-version").values_list("version", flat=True).first()
            or 0
        ) + 1
        version = RegistryRecordVersion.objects.create(
            record=locked,
            schema=schema,
            version=next_version,
            data=data,
            sequence_revision=sequence_revision,
            change_summary=change_summary,
            created_by=actor,
        )
        locked.schema = schema
        locked.current_version = version
        locked.save(update_fields=["schema", "current_version", "updated_at"])
    record.current_version = version
    record.schema = schema
    record_audit_event(
        entity=record,
        action=audit_action,
        actor=actor,
        after={
            "version": version.version,
            "schema": f"{schema.code}:{schema.version}",
            "sequence_revision": (
                str(sequence_revision.public_id) if sequence_revision else None
            ),
        },
        details={"change_summary": change_summary},
    )
    return version


def duplicate_matches(
    *,
    user,
    schema,
    registry_id="",
    aliases=None,
    catalog_number="",
    sequence_checksum="",
    data=None,
    exclude_record=None,
):
    aliases = [str(item).strip() for item in (aliases or []) if str(item).strip()]
    data = data or {}
    queryset = registry_records_for_user(user).select_related("current_version", "schema")
    if exclude_record:
        queryset = queryset.exclude(pk=exclude_record.pk)

    reasons = {}

    def add(record_id, reason):
        reasons.setdefault(record_id, set()).add(reason)

    if registry_id:
        for record_id in queryset.filter(registry_id__iexact=registry_id).values_list("id", flat=True):
            add(record_id, "registry_id")
    if catalog_number:
        for record_id in queryset.filter(catalog_number__iexact=catalog_number).values_list("id", flat=True):
            add(record_id, "catalog_number")
    if sequence_checksum:
        for record_id in queryset.filter(
            current_version__sequence_checksum=sequence_checksum
        ).values_list("id", flat=True):
            add(record_id, "sequence_checksum")
    if aliases:
        alias_query = Q()
        for alias in aliases:
            alias_query |= Q(alias__iexact=alias)
        alias_ids = RegistryAlias.objects.filter(
            alias_query,
            record__in=queryset,
        ).values_list("record_id", flat=True)
        for record_id in alias_ids:
            add(record_id, "alias")

    matching_fields = [str(item) for item in (schema.matching_fields or [])]
    if matching_fields:
        for candidate in queryset.filter(schema__entity_type=schema.entity_type):
            candidate_data = candidate.current_version.data if candidate.current_version else {}
            matched = [
                field
                for field in matching_fields
                if data.get(field) not in (None, "")
                and candidate_data.get(field) == data.get(field)
            ]
            if matched and len(matched) == len(
                [field for field in matching_fields if data.get(field) not in (None, "")]
            ):
                add(candidate.id, "matching_fields:" + ",".join(matched))

    records = queryset.filter(id__in=reasons).select_related("schema", "current_version")
    return [
        {
            "public_id": str(record.public_id),
            "registry_id": record.registry_id,
            "name": record.name,
            "entity_type": record.schema.entity_type,
            "lifecycle_status": record.lifecycle_status,
            "reasons": sorted(reasons[record.id]),
        }
        for record in records
    ]
