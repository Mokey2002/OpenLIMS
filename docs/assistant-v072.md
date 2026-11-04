# Assistant v0.72: five lab workflows in chat

Both the Assistant page and floating widget offer these workflows inline. Ask for one, fill the exact missing fields, review the preview and exclusions, and confirm with the existing action controls. Opening a form or replying “yes” in conversation does not execute it. The rules-based routes work without a language model; open-ended interpretation still depends on an enabled provider.

| Capability | Example | Confirmed result |
| --- | --- | --- |
| Batch management | “Assign ALPHA’s unassigned work to maria and set Friday deadlines” | Sets eligible work-item assignment/deadline metadata together. Choose an exact date/time in the form; no Friday time is guessed. |
| Resource planning | “Book instrument SEQ-1 in project ALPHA” | Creates an instrument booking and optional reagent stock reservations atomically. |
| Import repair | “Repair import #40” | Validates selected originally rejected rows into a separate child import, then queues it after confirmation. |
| Notebook draft | “Create a notebook draft from import #40 in project ALPHA” | Creates a native Draft experiment with actual run evidence, revisions and source links in a selected writable notebook. |
| Shift handover | “Hand my unfinished ALPHA work to maria” | Reassigns eligible unfinished work and optionally creates the previewed internal notification. |

Starter prompts are **Manage batch work**, **Reserve resources**, **Repair rejected import rows**, **Create a notebook draft from this run**, and **Prepare a shift handover**. Completed import receipts also offer **Repair rejected rows**. “This run” can use a currently accessible completed import or the current workflow guide; the destination notebook must be chosen explicitly. Follow-ups such as “Use project ALPHA” update the inline scope. Unsupported extra batch conditions are refused rather than widening the selection.

## Preview and confirmation rules

- Active Tech/Admin users can change work metadata, reserve resources and repair their own assistant imports. Notebook drafts follow native notebook write access, including explicitly authorized editors. Current project, sample, target user and source access are checked again at confirmation.
- Previews freeze the requested fields and a digest of relevant records. Confirmation locks and rereads current records. A change in eligibility, assignment, deadlines, stock, notebook audience, source evidence or permissions requires a fresh preview. Confirming the same action again recovers its stored result without repeating changes.
- Batch updates and handovers assess the complete selected unfinished scope (project, optional batch, unassigned/mine/team or exact source user). At most 100 candidates are allowed; larger scopes must be narrowed. Final/failed/inaccessible/no-change work is disclosed as excluded. Failed source evidence and workflow blockers are shown. Ownership changes do not start/complete work, bypass dependencies or approve QC.
- A handover notification is an internal OpenLIMS notification, created once only after successful confirmation. No email, Slack or external message is sent.
- Assistant-tagged audit entries are visible to their requesting actor and administrators. Existing non-assistant audit visibility is unchanged. Action detail/receipt access and current project/source access remain authoritative.
- Only the newest active form is editable. Current options are fetched again on refresh; revoked access hides stale options and disables preview. A failed preview request preserves selected repair edits for a safe retry. Saved conversations retain small form defaults, reread current access and never replay actions or repair corrections.

## Resource planning

Choose one configured instrument, an explicit future start/end and up to ten reagent lots with positive quantities and compatible units. The UI uses the displayed browser time zone and sends an offset-bearing timestamp. Naive server timestamps are rejected. Windows may span at most 14 days; adjacent half-open windows are allowed.

Availability covers OpenLIMS bookings only. It does not establish physical readiness or synchronize external calendars. Stock must be active, unquarantined, sufficiently available and unexpired through the end date. A reservation reduces available stock immediately; it does not consume stock or start a run. Conflicts and stock shortages leave no partial booking/reservation.

Use the same form’s cancellation mode, or “Cancel booking #9 in project ALPHA”. Only the creator or an administrator can cancel. Confirmation cancels the booking and releases linked ACTIVE reservations; consumed quantities are preserved. Receipts include booking/reservation IDs.

PostgreSQL row locks serialize conflicting instrument bookings across projects and competing stock requests. A PostgreSQL exclusion constraint also prevents overlapping ACTIVE bookings inserted outside the assistant. These guarantees are tested on PostgreSQL with its default READ COMMITTED isolation, matching native inventory operations; SQLite is suitable for basic development only and skips that exclusion constraint/concurrency suite.

## Rejected-row repair and data accounting

Repair applies to the original uploader’s completed/failed assistant-prepared imports. Data row numbers count records after the configured instrument header, not raw file lines. The server reads the preserved original file with its frozen mapping to identify rejected records. Successful original rows cannot be selected. The UI shows up to 20 rejected rows per page; one child contains at most 20 corrected rows. Paging/refresh is disabled while corrections are selected to prevent silent loss.

Only sample-ID and currently mapped columns may be corrected. Enter actual values; the assistant does not invent measurements. A changed mapping is disclosed and used to validate the corrected child. All selected rows must validate before a confirmation is offered. Native duplicate-row handling remains explicit. Child files use the protected assistant-artifact storage prefix; reports/receipts require current authorized access.

The original file, original receipt and imported measurements are preserved. The child stores its own checksum, original import/run/checksum, source-row list and correction digest. The row ledger allows one current child per original row. Repeating the same preview recovers the child; a completed repair cannot be imported again with different corrections. Queued/running repairs cannot be replaced. Replacing an unconfirmed/failed repair cancels its proposal and must include all rows it claimed. Superseded children fail confirmation, revalidation and worker claim checks.

The native QUEUE_IMPORT action, Celery worker, frozen mapping/access validation, progress/status recovery and row accounting perform the import. A repaired child receipt and CSV report identify the original data row. Retrying a confirmation does not create another import; failed preview transactions clean up newly stored child files and row claims.

## Notebook evidence

Select an accessible pipeline run or completed import and a writable project notebook in the same primary project, optionally with an active notebook template. At most 100 work items, 100 pipeline steps and 500 results are supported; oversized or cross-project source evidence is refused rather than partially copied. The audience check is bounded to 500 users.

Drafts include configured procedure codes/versions and recorded statuses, real measurements (including zero and false), units and separate automated QC/human-review states. Instrument mappings are identified as data conversion, not a physical method. Actual method notes are explicit user input. The draft does not invent conclusions or infer scientific completion, QC approval or release readiness. Recorded reason/note excerpts are bounded and labeled.

The experiment remains **DRAFT**, uses native revisions/checksums/source links, and opens through the returned notebook link. A selected template initializes its configured workflow steps and can create native internal assignment notifications; those steps/assignees and the notification warning are shown in the preview. All current notebook readers must be able to access the source samples. Concurrent previews cannot silently create duplicate drafts from the same snapshot; a competing creation makes the other preview stale. This is snapshot-based protection, not a permanent prohibition on intentionally making a later draft.

## API

All endpoints require authentication and exist under both `/api/` and `/api/v1/`:

| Endpoint | Purpose |
| --- | --- |
| `GET assistant/lab-operations/options/?kind=batch&project=ALPHA` | Current permitted choices for `batch`, `resources`, `repair`, `notebook` or `handover`. Selectors show at most 100 entries; exact IDs/codes are validated again. |
| `POST assistant/lab-operations/preview/` | Body `{ "kind": "…", "fields": { … } }`; returns a form/eligibility explanation or the native `pending_action`. |
| `GET assistant/import-repairs/40/?offset=0` | Current authorized rejected data rows and repair status. |
| `POST assistant/actions/<confirmation_token>/confirm/` | Body `{ "confirm": true }`; executes the frozen action, or queues a repaired import. |
| `GET assistant/instrument-imports/<id>/` | Current import receipt and complete accounting counts. |

Example preview fields (submit only the fields for the selected operation):

```json
{"kind":"batch","fields":{"project":"ALPHA","batch":"B-100","scope":"unassigned","assign_to":"maria","deadline_mode":"set","due_at":"2026-12-04T17:00:00-08:00"}}
```

```json
{"kind":"resources","fields":{"project":"ALPHA","instrument":"SEQ-1","starts_at":"2026-12-04T10:00:00-08:00","ends_at":"2026-12-04T12:00:00-08:00","stocks":[{"lot":"LOT-1","quantity":"2","unit":"ml"}],"note":"Planned sequencing run"}}
```

```json
{"kind":"repair","fields":{"parent_id":40,"skip_duplicates":true,"corrections":[{"row":2,"values":{"value":"12"}}]}}
```

```json
{"kind":"notebook","fields":{"project":"ALPHA","source_kind":"import","source_id":40,"notebook_id":3,"template_id":null,"title":"Run evidence for review","method_notes":"Actual execution notes supplied by the scientist"}}
```

```json
{"kind":"handover","fields":{"project":"ALPHA","source":"me","recipient":"maria","send_notice":true,"message":"Review the recorded blockers before proceeding."}}
```

## Deployment and validation

Version/footer: **0.72.0**. Both READMEs retain exactly **v0.72, v0.71 and v0.70** release updates. No new Python/Node dependency or service is required.

Apply four migrations: `assistant.0010`, `imports.0008`, `inventory.0006` and `inventory.0007`. The last migration enables PostgreSQL’s bundled `btree_gist` extension, then creates the booking exclusion constraint; the migration role needs permission to enable it (or an administrator can install it first). Reversal removes the constraint but preserves the shared extension. Rebuild the API/frontend and restart Celery workers with the same backend version so repaired-job claim checks and audit tagging run in workers too. Existing assistant-artifact media-path blocking from v0.70 must be installed.

Regression tests cover native writes/receipts, permission revocation, stale evidence, units/stock/booking conflicts, failed transaction cleanup, repair lineage and supersession, notebook readers/templates, private assistant audit entries, concurrent PostgreSQL requests, real authenticated HTTP/SSE and both browser chat surfaces. Exact release validation counts belong in the PR. Browser tests simulate API responses; real HTTP tests exercise the actual database services. Live OpenAI/Ollama conversational quality is not claimed when the provider is disabled.
