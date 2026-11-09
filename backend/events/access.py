"""Read audit records through current object permissions, before pagination."""
from django.apps import apps
from django.conf import settings
from django.db.models import (
    BigIntegerField, Case, CharField, Exists, F, IntegerField, OuterRef, Q,
    Subquery, UUIDField, Value, When,
)
from django.db.models.fields.json import KT
from django.db.models.functions import Cast, Lower, Replace

from core.entities import get_accessible_entity_queryset, supported_entity_types
from core.permissions import is_admin
from core.project_access import get_project_access_queryset
from projects.models import Project


# These older modules do not use the shared entity registry yet. Their audit
# reads still require real object/project ownership, never just a payload claim.
PROJECT_ENTITIES = {
    "samplebatch": ("samples.SampleBatch", None),
    "importjob": ("imports.ImportJob", "uploaded_by"),
    "alignmentjob": ("alignments.AlignmentJob", "created_by"),
    "blastjob": ("blast.BlastJob", "created_by"),
    "massspecrun": ("mass_spec.MassSpecRun", "uploaded_by"),
    "migrationjob": ("migration_toolkit.MigrationJob", "uploaded_by"),
}
GLOBAL_ENTITIES = {
    "analysisdefinition": "pipelines.AnalysisDefinition",
    "proceduredefinition": "pipelines.ProcedureDefinition",
    "pipelinetemplate": "pipelines.PipelineTemplate",
    "blastdatabase": "blast.BlastDatabase",
}
REFERENCE_PATHS = ("entity", "details__target")
PROJECT_PATHS = (
    "project_id", "project", "before__project_id", "after__project_id",
    "before__project", "after__project", "details__project_id", "details__project",
    "entity__project", "details__target__project",
)


def _kind(expression):
    # Both legacy model class names and shared snake_case names are in use.
    return Lower(Replace(expression, Value("_"), Value(""), output_field=CharField()))


def _identifier_aliases(queryset, lookup):
    # Validate the untrusted text before casting it. Cast the event value, so
    # the target's primary/public ID indexes remain available to the database.
    number = Q(**{f"{lookup}__regex": r"^[0-9]{1,18}$"}) | (
        Q(**{f"{lookup}__regex": r"^[0-9]{19}$"}) & Q(**{f"{lookup}__lte": "9223372036854775807"})
    )
    uuid = Q(**{f"{lookup}__regex": r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"})
    return queryset.alias(**{
        f"{lookup}_integer": Case(When(number, then=Cast(lookup, BigIntegerField())), output_field=BigIntegerField()),
        f"{lookup}_uuid": Case(When(uuid, then=Cast(lookup, UUIDField())), output_field=UUIDField()),
    })


def _identifiers(queryset, lookup):
    primary = queryset.model._meta.pk
    key = f"{lookup}_uuid" if isinstance(primary, UUIDField) else f"{lookup}_integer" if isinstance(primary, IntegerField) else lookup
    predicate = Q(pk=OuterRef(key))
    if any(field.name == "public_id" for field in queryset.model._meta.fields):
        predicate |= Q(public_id=OuterRef(f"{lookup}_uuid"))
    return Q(Exists(queryset.filter(predicate)))


def _project_context(queryset, project_keys):
    """A readable target must not expose another project's historical snapshot.

    Metadata can restrict access but cannot establish it. Unresolved project
    references are retained for administrators instead of trusting old payloads.
    """
    for index, path in enumerate(PROJECT_PATHS):
        scalar = f"_audit_project_{index}"
        public_id = f"_audit_project_uuid_{index}"
        queryset = queryset.alias(**{
            scalar: KT(f"payload__{path}"),
            public_id: KT(f"payload__{path}__public_id"),
        }).filter(
            Q(**{f"{scalar}__isnull": True}) | Q(**{scalar: ""})
            | Q(**{f"{scalar}__in": project_keys})
            | Q(**{f"{public_id}__in": project_keys})
        )
    return queryset


def _readable_entities(user, kinds, project_keys):
    registered = {name.replace("_", ""): name for name in supported_entity_types()}
    blocked = set()
    if getattr(settings, "OPENLIMS_ENFORCE_FEATURE_FLAGS", True):
        from settings_app.models import SystemSettings

        if kinds & {"notebook", "experiment", "experimenttemplate", "registryrecord"}:
            flags = SystemSettings.load().feature_flags
            if not flags.get("notebook", False):
                blocked.update({"notebook", "experiment", "experimenttemplate"})
            if not flags.get("registry", False):
                blocked.add("registryrecord")

    readable = {}
    notebook_ids = None
    for kind in kinds - blocked:
        if kind in {"notebook", "experiment", "experimenttemplate"}:
            from notebook.permissions import notebooks_for_user

            # Resolve this request's notebook sharing directory once. Repeating
            # all sharing joins inside every nested audit reference makes the
            # database plan unnecessarily expensive, even for a small page.
            if notebook_ids is None:
                notebook_ids = list(notebooks_for_user(user).order_by().values_list("pk", flat=True))
            label = {"notebook": "Notebook", "experiment": "Experiment", "experimenttemplate": "ExperimentTemplate"}[kind]
            key = "pk__in" if kind == "notebook" else "notebook_id__in"
            readable[kind] = apps.get_model(f"notebook.{label}").objects.filter(**{key: notebook_ids})
        elif kind == "sopdocument":
            from assistant.sop_operations import _accessible_documents

            readable[kind] = _accessible_documents(user)
        elif kind in registered:
            readable[kind] = get_accessible_entity_queryset(registered[kind], user)
        elif kind in PROJECT_ENTITIES:
            label, owner = PROJECT_ENTITIES[kind]
            readable[kind] = get_project_access_queryset(
                apps.get_model(label).objects.all(), user, owner_lookup=owner,
            )
            if kind == "migrationjob":
                readable[kind] = readable[kind].exclude(profile__source_type="DATABASE")
        elif kind in GLOBAL_ENTITIES:
            readable[kind] = apps.get_model(GLOBAL_ENTITIES[kind]).objects.all()
        elif kind == "assistantaction":
            readable[kind] = _project_context(
                apps.get_model("assistant.AssistantAction").objects.filter(requested_by=user), project_keys,
            )
        elif kind == "notificationsubscription":
            readable[kind] = apps.get_model("assistant.NotificationSubscription").objects.filter(
                Q(created_by=user) | Q(recipient=user),
            )
        elif kind == "sampleform":
            model = apps.get_model("custom_fields.SampleForm")
            latest = model.objects.filter(code=OuterRef("code"), published=True).order_by("-pk")
            readable[kind] = model.objects.filter(
                pk=Subquery(latest.values("pk")[:1]), archived=False,
            )
    return readable


def events_for_user(queryset, user):
    if not user or not user.is_authenticated:
        return queryset.none()
    if is_admin(user):
        return queryset

    annotations = {"_audit_kind": _kind(F("entity_type"))}
    for index, path in enumerate(REFERENCE_PATHS):
        annotations[f"_audit_ref_kind_{index}"] = _kind(KT(f"payload__{path}__type"))
    # Discover only distinct types, not individual audit rows. Native permission
    # querysets become SQL subqueries so counts, detail reads and pages agree.
    types = list(queryset.order_by().annotate(**annotations).values_list(*annotations).distinct())
    primary_kinds = {row[0] for row in types if row[0]}
    reference_kinds = [{row[index + 1] for row in types if row[index + 1]} for index in range(len(REFERENCE_PATHS))]
    kinds = primary_kinds.union(*reference_kinds)
    # Reuse the current request's small project directory for snapshot checks;
    # repeating its membership subquery for every JSON path is very expensive.
    project_keys = [
        str(identifier) for pk, public_id in Project.objects.filter(members=user).values_list("pk", "public_id")
        for identifier in (pk, public_id)
    ]
    readable = _readable_entities(user, kinds, project_keys)
    queryset = _identifier_aliases(queryset.alias(**annotations), "entity_id")
    visible = Q(pk__in=[])
    for kind, entities in readable.items():
        if kind in primary_kinds:
            visible |= Q(_audit_kind=kind) & _identifiers(entities, "entity_id")
    queryset = queryset.filter(visible)

    # Common audit snapshots can reference a second private object (for example
    # an experiment linked to a readable sample). Check both ends of that link.
    for index, path in enumerate(REFERENCE_PATHS):
        snapshot = f"_audit_snapshot_{index}"
        identifier = f"_audit_ref_id_{index}"
        queryset = queryset.alias(**{
            snapshot: KT(f"payload__{path}"),
            identifier: KT(f"payload__{path}__public_id"),
        })
        queryset = _identifier_aliases(queryset, identifier)
        visible_reference = Q(**{f"{snapshot}__isnull": True})
        for kind, entities in readable.items():
            if kind in reference_kinds[index]:
                visible_reference |= Q(**{f"_audit_ref_kind_{index}": kind}) & _identifiers(entities, identifier)
        queryset = queryset.filter(visible_reference)

    private = Q(_audit_kind="assistantaction") | Q(payload__has_key="assistant_action_id")
    queryset = queryset.exclude(private & ~Q(actor=user))
    return _project_context(queryset, project_keys)
