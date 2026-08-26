# OpenLIMS v0.25.1 shared foundation

This release establishes the contracts that Notebook, Registry, Studies,
Insight, and other modules must reuse. It intentionally keeps the existing
numeric primary keys and `/api/` endpoints so current clients continue to work.

## Public entity identity

Externally linkable records inherit `core.models.PublicIDModel`. The generated
UUID is immutable through serializers and is never reused as a database foreign
key. APIs continue to expose the existing numeric `id` alongside `public_id`.

The stable entity type names are:

| Area | Entity type |
|---|---|
| Project | `project` |
| Sample | `sample` |
| Molecular Biology | `sequence` |
| Inventory | `location`, `container`, `inventory_item`, `inventory_lot`, `inventory_reservation` |
| Workflows | `pipeline_run` |
| Registry (reserved) | `registry_record` |
| Notebook (reserved) | `experiment` |
| Studies (reserved) | `study` |

An external entity reference is always `{type, public_id}`. Future modules add
their model to `core.entities` before enabling links or attachments.

## Object links

`POST /api/v1/entity-links/` creates a directed relationship between two
registered entities. The request supplies source and target entity references,
a lowercase `relation_type`, and optional label and JSON metadata.

Rules:

- An entity cannot link to itself.
- The same directed relation cannot be created twice.
- Two project-scoped records must share their primary project.
- A project-scoped record must be assigned to a primary project before it can
  use shared links or attachments; this prevents projectless private records
  from becoming visible through a global relationship.
- Directors can access all records.
- Project members can read links for their projects.
- Only directors and technicians with project access can create or remove links.
- Every create or delete writes the common audit payload.

## Shared attachments

`POST /api/v1/shared-attachments/` accepts a file and one target entity
reference. The service applies the global upload-size setting, an allowlist of
file types, a safe storage path, media type and byte-size capture, and a SHA-256
digest. Visibility and modification use the same project rules as links.

New modules must use this service instead of adding another generic attachment
foreign key. Existing sample-specific attachment APIs remain unchanged for
backward compatibility and can be migrated separately.

## Project permissions

Use these shared helpers for new module querysets and object actions:

- `core.project_access.get_project_access_queryset`
- `core.project_access.user_can_access_project`
- `core.project_access.require_project_access`
- `core.permissions.ProjectScopedEntityPermission`
- `core.entities.resolve_entity`

The standard behavior is all records for directors, project-member records for
authenticated readers, and project-member writes for directors or technicians.
Objects explicitly registered as globally scoped use role checks without a
project filter.

## Audit events

New modules call `core.audit.record_audit_event`. Payload schema version 1 is:

```json
{
  "schema_version": 1,
  "entity": {"type": "sample", "public_id": "...", "label": "S-1042"},
  "project": {"public_id": "...", "code": "PRJ-1", "name": "Project 1"},
  "reason": "User-supplied reason when required",
  "before": {},
  "after": {},
  "details": {}
}
```

The event's top-level `entity_type` and `entity_id` use the stable entity type
and public ID. Modules may add fields only inside `details` until the audit
schema version changes.

## API versioning and schema

- Current versioned base: `/api/v1/`
- OpenAPI document: `/api/schema/`
- Interactive documentation: `/api/docs/`
- Legacy compatibility base: `/api/`

The initial schema publishes the versioned surface. Existing clients can remain
on `/api/`; new integrations should start on `/api/v1/`.

## Feature flags and localization

Notebook, Registry, Studies, and Insight are disabled by default. A director can
change the flags in **Admin → Settings → Feature Flags**. Authenticated clients
can read effective values from `/api/v1/feature-flags/`.

Every new flag definition contains English (`en`) and Spanish (`es`) labels and
descriptions. `npm run check:i18n` fails when either language is missing, and it
runs automatically before a production frontend build.

## Checklist for a new module

1. Keep the module behind its system feature flag until its exit criteria pass.
2. Inherit public records from `PublicIDModel` and expose `public_id` read-only.
3. Register linkable models under their reserved entity type.
4. Scope querysets and object actions through the shared permission helpers.
5. Emit the versioned common audit payload.
6. Use shared entity links and attachments.
7. Publish routes under `/api/v1/` and verify the OpenAPI schema.
8. Supply and validate English and Spanish user-facing strings.
