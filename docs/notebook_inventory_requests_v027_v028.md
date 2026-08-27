# OpenLIMS v0.27–v0.28: Notebook, Inventory, and Workflow Requests

This release adds an immutable collaborative experiment notebook, a custody-
oriented inventory ledger, and internal assay request intake. Existing `/api/`
routes remain available; the same resources are also published under
`/api/v1/` and in `/api/docs/`.

## Notebook v1

Notebooks can be scoped to one user, a team, or a project. Explicit reader,
editor, commenter, reviewer, and locker assignments are combined with project
membership and laboratory roles. Each experiment moves through draft,
in-progress, completed, reviewed, and locked states.

Every save creates an immutable `ExperimentRevision` only when the content has
changed. A revision owns ordered immutable blocks and exact linked-object
snapshots. Restoring history creates another revision instead of overwriting an
old one. Supported blocks are rich text, heading, table, checklist, protocol
step, calculation, image, attachment, structured result, and embedded sequence
view.

Links address stable `{entity_type, public_id}` records and capture the version
visible at save time. Registry and sequence revisions, SOP versions, samples,
inventory lots, pipeline runs, work items, and results are supported. Comments,
mentions, and assignments remain available after sign-off without changing the
locked revision.

An approved review records the revision checksum, reviewer, timestamp, signed
name, and decision. Locking requires an approval for the current checksum.
These controls are an internal sign-off mechanism, not yet a regulated
electronic-signature implementation. PDF export includes the content, authors,
reviewers, timestamps, revision checksums/history, and linked-record versions.

## Inventory v2

Locations use the hierarchy site, building, laboratory, room, freezer, shelf,
rack, box, and well. Containers can define plate dimensions, and placements
assign a sample or inventory lot to a validated position. Generic barcode
identities resolve locations, containers, samples, reagent lots, registered
materials, and other shared entities.

Inventory quantities change through an immutable transaction service. Receive,
move, transfer, count, consume, adjust, quarantine, dispose, and return entries
capture actor, reason, amount, unit, before/after quantity and status, locations,
containers, work item, experiment, and request item. Direct quantity/status/
location updates through the lot API are rejected.

Inventory items and lots include commercial, storage, cost, chemical, hazard,
GHS, SDS, COA, and disposal metadata. Expiration, low-stock, reorder, and
reservation alerts can be refreshed through the API. Cycle counts freeze the
expected quantity, accept observed values, and reconcile variances through the
same ledger.

## Workflow Requests v1

Directors configure assay request types with JSON submission schemas, default
pipelines, priority, SLA, and material, instrument, personnel, or duration
requirements. Project members submit accessible samples or Registry records.
Laboratory staff triage, while directors approve or reject.

Approval creates dependency-aware pipeline runs, optionally groups them by
batch or plate, and reserves required inventory lots in expiration order.
Technicians execute the existing work queue and scan consumed lots against the
work/request provenance. Requesters can see status, step execution, QC, results,
public messages, their attachments, and approved reports. Internal-only messages
and unapproved reports are staff-only. The external requester portal is not part
of this release.

## Demo and verification

Run migrations and the idempotent comprehensive seed on a development or
staging deployment:

```bash
python manage.py migrate
python manage.py seed_demo
```

The seeder does not create, request, show, or change passwords. Use an existing
administrator account. It enables Registry and Notebook and creates a signed,
locked experiment; exact object/version links; hierarchical inventory;
barcodes; plate placements; ledger entries; alerts; a cycle count; a sequencing
request; automatic reservations; work execution; messages; an attachment; and
an approved report.

Focused tests:

```bash
pytest notebook/tests/test_notebook_v1.py \
  workflow_requests/tests/test_inventory_workflow_requests_v2.py \
  core/tests/test_seed_demo.py -q
```
