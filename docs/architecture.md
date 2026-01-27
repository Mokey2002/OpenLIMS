# OpenLIMS Architecture

OpenLIMS is a lightweight LIMS backend designed to run with minimal setup:
- Django + Django REST Framework (API + Admin)
- PostgreSQL (system of record)
- Docker Compose (one-command startup)

## High-level diagram


## Django apps and responsibilities

### `samples`
- Core entity: `Sample`
- Tracks sample identity and lifecycle fields
- Connected to inventory via `Sample.container -> inventory.Container`

### `inventory`
- `Location` (freezer/rack/shelf/etc.)
- `Container` (tube/box/plate)
- Relationship: `Location -> Container -> Sample`

### `events`
- `Event` is the audit trail
- Automatic events are generated on create/update/delete of:
  - Sample
  - Container
  - Location

### `custom_fields`
- Configurable metadata without migrations
- `FieldDefinition`: defines a field (name/type/rules) for an entity type (v1: Sample)
- `FieldValue`: stores values per entity instance
- Validation enforces data types and rules (min/max/choices/regex/etc.)

## Key APIs

- `/health` — service + DB connectivity check
- `/api/samples/` — CRUD samples
- `/api/locations/` — CRUD locations
- `/api/containers/` — CRUD containers
- `/api/events/` — read-only audit log
- `/api/field-definitions/` — CRUD custom field definitions
- `/api/field-values/` — CRUD custom field values
- `/api/samples/<id>/custom-fields/` — resolved view of a sample’s custom fields

## Audit trail (Events)

Events are created automatically (signals) and include:
- entity type + id
- action (CREATED/UPDATED/DELETED)
- timestamp
- payload snapshot
