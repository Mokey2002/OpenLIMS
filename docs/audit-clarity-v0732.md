# Assistant audit records and readable activity

OpenLIMS v0.73.2 removes redundant writes in assistant notebook creation and
completion receipts, and shows meaningful audit labels in Dashboard activity,
Audit Events and Reports. Real changes remain independently auditable.

## Causes and corrections

| Cause | Correction |
| --- | --- |
| A template-based assistant draft initialized a template revision and then wrote a second revision containing the evidence. | Compose template blocks and recorded evidence before the first save. Keep workflow initialization in the canonical draft-creation audit payload. |
| Draft creation wrote a native revision event and a separate draft-created event for the same initialization. | Write one `DRAFT_CREATED_FROM_RUN` event with the revision, changes, source action and initial workflow snapshot. |
| Synchronous confirmation wrote both confirmed and completed receipts at the same instant. | Write one completed receipt, retaining `confirmed_at`, task summary and result. Queued work still logs confirmation and its later outcome separately. |
| Revision checksums depended on link input order, but the API returned links sorted by type/label. | Compare actual stored content using a stable link order. Preserve existing immutable checksums. |
| An identical retry using the original base revision was treated as a conflicting edit. | Reuse the current receipt if the requested content is identical; reject genuinely different stale edits. |
| Notebook retry feedback could omit the recovered revision or show the wrong draft status. | Merge revision history by public ID and return the server's actual `experiment_status` in the autosave receipt. |

These are specific redundant-write paths, rather than a rule deleting entries
with similar timestamps. Multiple actual edits still create separate revisions.
Confirmation retries reuse the same assistant action and do not repeat its
business operation. Existing audit rows, revision bodies, signatures and stored
checksums are preserved.

## Reading the activity

| Previously shown | Now shown |
| --- | --- |
| `EXPERIMENT_REVISION_CREATED`, experiment UUID | **Experiment saved — Protein stability study**, with **Revision 3 → 4; 1 block modified**. |
| `CONTAINER_CREATED`, `Container #13` | **Container created — Protein box A**, using the recorded container identifier. |
| `LOCATION_CREATED`, `Location #18` | **Location created — Protein freezer**, using the recorded name. |
| Assistant action UUID | Readable assistant state and the recorded task summary. |

Audit Events keeps the raw action code, record/event IDs and complete payload
inside **Technical details**. Older assistant reasons hide the redundant action
UUID in the normal row while retaining the original payload there. A historical
record without a stored name displays **name unavailable** instead of inventing
one. Genuine edits show their revision numbers and, for new entries, counts of
added, removed and modified blocks/links.

The original metadata remains available for investigation. No time-based
deduplication hides distinct edits, attempts or independent actions. No live
record lookup is needed to render a label: descriptions use the already
authorized snapshot. Private notebook/project checks, actor privacy and
admin-only export rules remain in force.

English and Spanish UI descriptions are supported. Audit CSV and JSON exports
append `entity_label`, `action_label`, `description` and `source`, preserving the
original fields. New user-controlled CSV labels are escaped as spreadsheet
text. Reports' audit-activity CSV adds the same readable fields.

Applying or clearing Audit Events filters cancels the previous load. A late
response cannot replace newer results. Clearing filters also reloads the list.

## Upgrade

This branch carries forward the pending v0.73.1 administrator-safety commit, so
it contains both requested fixes. Installations upgrading from v0.73.0 need
**core.0004_user_administration_lock**. The audit changes themselves require no
new schema or historical-data rewrite.

Rebuild/recreate **api**, **worker** and **web** from this checkout. Production
Compose runs migrations before starting the API:

```bash
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml up -d --build api worker web
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml logs --tail=80 api
```

Use your installation's existing project name and environment file. Custom
deployments must apply migrations before API traffic. Refresh the browser and
check footer **0.73.2**. Both READMEs keep exactly **0.73.2, 0.73.1 and 0.73.0**
release updates.

## Verification

Backend tests cover one initial assistant draft revision, preserved workflow
and evidence, one synchronous completion receipt, repeated confirmation,
unchanged saves, legacy hashes, link reordering, stale edit rejection, actual
change counts, private audit visibility, malformed snapshots, readable exports
and bounded query counts. PostgreSQL tests also race identical saves.

```bash
docker compose -f deploy/docker-compose.yml exec -T api pytest -q notebook/tests/test_audit_revisions.py notebook/tests/test_concurrency.py events/test_presentation.py assistant/tests/test_actions.py assistant/tests/test_lab_operations.py
```

Browser tests in `frontend/e2e/tests/audit-clarity.spec.js` use controlled API
responses with the real UI to check Dashboard/Audit Events descriptions,
technical details, filter races, Spanish and notebook save recovery. Backend
API tests use real PostgreSQL; they do not infer authorization from browser mocks.
