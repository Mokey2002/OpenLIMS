# OpenLIMS Assistant Phases 6-11

OpenLIMS keeps assistant writes deterministic and confirmation-gated. The assistant may prepare an exact preview, but it cannot execute a Phase 6, 7, 8, or 10 write until the requesting user explicitly confirms the time-limited action token. Permissions and frozen record snapshots are checked again during execution.

## Phase 6: work items

- Read overdue or unassigned work through project-scoped queries.
- Create work for the exact frozen samples in a batch.
- Assign or reassign active work with project-membership and workload context.
- Prevent duplicate active work for the same sample and work type.
- Prevent completed or cancelled work from being reassigned.
- Audit work creation and assignment changes.

## Phase 7: barcodes and labels

- Generate Code 128 sample labels from an exact sample, range, or batch.
- Produce a downloadable PDF with up to 100 labels per confirmed action.
- Maintain a unique barcode-to-sample mapping.
- Mark previously generated labels as reprints in the preview and PDF.
- Audit original generation and every reprint.

## Phase 8: audit and compliance reports

- Interpret report type, project, sample, user, date range, time zone, and output format before confirmation.
- Generate CSV audit exports and PDF project/compliance reports.
- Apply project and role permissions during both preview and generation.
- Store the exact filter parameters and SHA-256 checksum with every artifact so it can be reproduced and verified.
- Audit export generation.

## Phase 9: documentation and SOP answers

- Answer only from approved, current OpenLIMS documents and SOP sections accessible to the user.
- Cite document code, version, and section in every supported answer.
- Exclude archived, unapproved, project-restricted, and role-restricted documents.
- State clearly when the approved documentation does not contain an answer.
- Keep informational answers separate from operational proposals.

Administrators manage SOP records through `/api/sop-documents/` or Django Admin.

## Phase 10: notifications and scheduled summaries

- Store the trigger, recipient, delivery channel, frequency, expiration, project scope, target, and optional threshold.
- Support BLAST completion, sample approval, pending-QC, and low-inventory triggers.
- Prevent duplicate active subscriptions while allowing a cancelled subscription to be recreated.
- List and cancel subscriptions through the assistant.
- Recheck recipient activity and project permission at delivery time.
- Prevent duplicate deliveries with a trigger-specific event key.
- Audit subscription creation, cancellation, delivery, and permission-denied skips.

Celery Beat dispatches due subscriptions every five minutes through `assistant.tasks.dispatch_due_notifications`.

## Phase 11: system monitoring

- Admin-only, read-only status for API, database, Redis, workers, queue depth, active tasks, recent failures, stuck imports/BLAST/alignments, storage, and backups.
- Return only sanitized availability states and counts; configuration values and connection strings are never included.
- Attach each warning to an internal diagnostic page.
- Expose the same sanitized view at `/api/assistant/system-monitoring/`.

## Artifact downloads

Generated label and report files are available only to the creator, an administrator, or an authorized member of the artifact's project. Downloads use `/api/assistant/artifacts/<artifact-id>/download/` and require normal OpenLIMS authentication.
