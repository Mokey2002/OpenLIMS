from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from django.contrib.contenttypes.models import ContentType

from core.permissions import is_admin, is_tech
from core.project_access import get_project_access_queryset, user_can_access_project


@dataclass(frozen=True)
class EntityDefinition:
    model: type
    label: Callable
    project: Callable
    owner_field: str | None = None
    global_scope: bool = False


# These names are the stable external identifiers used in links, attachments,
# audit payloads, and API routes. Future modules reserve their names here before
# their database models are enabled.
RESERVED_ENTITY_TYPES = frozenset(
    {
        "project",
        "sample",
        "sequence",
        "location",
        "container",
        "inventory_item",
        "inventory_lot",
        "inventory_reservation",
        "pipeline_run",
        "registry_record",
        "experiment",
        "study",
    }
)


def _definitions():
    # Imports stay local so the shared core contract does not create app cycles.
    from inventory.models import (
        Container,
        InventoryItem,
        InventoryLot,
        InventoryReservation,
        Location,
    )
    from pipelines.models import PipelineRun
    from projects.models import Project
    from samples.models import Sample
    from sequences.models import Sequence

    return {
        "project": EntityDefinition(
            Project,
            lambda obj: f"{obj.code} - {obj.name}",
            lambda obj: obj,
        ),
        "sample": EntityDefinition(
            Sample,
            lambda obj: obj.sample_id,
            lambda obj: obj.project,
            owner_field="created_by",
        ),
        "sequence": EntityDefinition(
            Sequence,
            lambda obj: obj.name,
            lambda obj: obj.project,
            owner_field="created_by",
        ),
        "location": EntityDefinition(
            Location,
            lambda obj: obj.name,
            lambda obj: None,
            global_scope=True,
        ),
        "container": EntityDefinition(
            Container,
            lambda obj: obj.container_id,
            lambda obj: None,
            global_scope=True,
        ),
        "inventory_item": EntityDefinition(
            InventoryItem,
            lambda obj: f"{obj.code} - {obj.name}",
            lambda obj: None,
            global_scope=True,
        ),
        "inventory_lot": EntityDefinition(
            InventoryLot,
            lambda obj: obj.lot_code,
            lambda obj: None,
            global_scope=True,
        ),
        "inventory_reservation": EntityDefinition(
            InventoryReservation,
            lambda obj: f"Reservation {obj.pk}",
            lambda obj: obj.project,
            owner_field="created_by",
        ),
        "pipeline_run": EntityDefinition(
            PipelineRun,
            lambda obj: f"{obj.sample.sample_id} - {obj.template_code}",
            lambda obj: obj.sample.project,
            owner_field="started_by",
        ),
    }


def supported_entity_types():
    return sorted(_definitions())


def get_entity_definition(entity_type):
    normalized = str(entity_type or "").strip().lower()
    definition = _definitions().get(normalized)
    if not definition:
        raise ValueError(
            f"Unsupported entity type '{entity_type}'. "
            f"Supported types: {', '.join(supported_entity_types())}."
        )
    return normalized, definition


def get_entity_type_for_object(obj):
    for entity_type, definition in _definitions().items():
        if isinstance(obj, definition.model):
            return entity_type
    raise ValueError(f"{obj._meta.label} is not registered as a linkable entity.")


def get_entity_project(obj):
    entity_type = get_entity_type_for_object(obj)
    return _definitions()[entity_type].project(obj)


def entity_is_globally_scoped(obj):
    entity_type = get_entity_type_for_object(obj)
    return _definitions()[entity_type].global_scope


def get_accessible_entity_queryset(entity_type, user, *, write=False):
    normalized, definition = get_entity_definition(entity_type)
    queryset = definition.model.objects.all()

    if not user or not user.is_authenticated:
        return queryset.none()
    if is_admin(user):
        return queryset
    if write and not is_tech(user):
        return queryset.none()
    if definition.global_scope:
        return queryset
    if normalized == "project":
        return queryset.filter(members=user).distinct()
    if normalized == "sample":
        from samples.access import get_sample_access_queryset

        return get_sample_access_queryset(queryset, user)
    if normalized == "pipeline_run":
        from samples.access import get_sample_access_queryset
        from samples.models import Sample

        allowed_samples = get_sample_access_queryset(Sample.objects.all(), user)
        return queryset.filter(sample__in=allowed_samples)

    return get_project_access_queryset(
        queryset,
        user,
        project_lookup="project",
        owner_lookup=definition.owner_field,
    )


def user_can_access_entity(user, obj, *, write=False):
    if not user or not user.is_authenticated:
        return False
    if is_admin(user):
        return True
    if write and not is_tech(user):
        return False

    entity_type = get_entity_type_for_object(obj)
    definition = _definitions()[entity_type]
    if definition.global_scope:
        return True
    if entity_type == "sample":
        from samples.access import user_can_access_sample, user_can_modify_sample

        checker = user_can_modify_sample if write else user_can_access_sample
        return checker(user, obj)

    project = definition.project(obj)
    if project is not None:
        return user_can_access_project(user, project, write=write)

    if definition.owner_field and is_tech(user):
        return getattr(obj, f"{definition.owner_field}_id", None) == user.pk
    return False


def resolve_entity(entity_type, public_id, user, *, write=False):
    normalized, _definition = get_entity_definition(entity_type)
    try:
        normalized_public_id = UUID(str(public_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("A valid entity public ID is required.") from exc

    obj = get_accessible_entity_queryset(
        normalized,
        user,
        write=write,
    ).filter(public_id=normalized_public_id).first()
    if obj is None:
        raise LookupError("No accessible entity matches that type and public ID.")
    if write and not user_can_access_entity(user, obj, write=True):
        raise PermissionError("You cannot modify links or attachments for this entity.")
    return obj


def entity_reference(obj):
    entity_type = get_entity_type_for_object(obj)
    definition = _definitions()[entity_type]
    project = definition.project(obj)
    reference = {
        "type": entity_type,
        "public_id": str(obj.public_id),
        "label": str(definition.label(obj)),
    }
    if project is not None:
        reference["project"] = {
            "public_id": str(project.public_id),
            "code": project.code,
            "name": project.name,
        }
    else:
        reference["project"] = None
    return reference


def content_object_fields(obj):
    return {
        "content_type": ContentType.objects.get_for_model(obj),
        "object_id": str(obj.pk),
    }
