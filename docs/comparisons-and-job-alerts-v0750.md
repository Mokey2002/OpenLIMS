# Visual comparisons and assistant job alerts — v0.75.0

## See the actual change

Open **Audit Events → Compare changes** to compare recorded fields side by side.
For example, a container move displays **Location: Freezer A → Freezer B**.
Sample moves and work assignments now capture readable reference names at the
time of the change. Renaming a location or account later does not rewrite that
history. Legacy events without names say that the historical name was not
recorded; original identifiers remain available in Technical details.

For notebook saves, select **Compare revision text** on the audit event. The same
view is available through **Notebook → History → Compare**. Removed words are
struck through in the before column; added words are underlined in the after
column. Added/removed blocks and changes to linked records are shown separately.
Initial revisions compare against empty content. Missing values, null, false and
numeric zero remain distinct. Complete raw snapshots are available in the
expandable technical details.

The comparison reads the exact immutable revisions referenced by the audit event.
It checks current event and notebook permissions, including private notebooks
and revoked project access. Changing the selected experiment cancels an old
comparison request so its response cannot replace a newer selection. Viewing a
comparison creates no revision, audit event or data mutation.

Content is rendered as text, including HTML-like source strings. It is never
inserted as executable HTML. Long values are explicitly shortened to 12,000 text
units per side; full data remains in Technical details. Word comparisons use a
bounded matching algorithm and fall back to highlighting the changed middle
section for very large edits. This keeps large records usable without implying
that the displayed excerpt is the complete record.

## Failure and stalled-job alerts

Assistant failures deliver one in-app notification to the requester. It includes
the last recorded completed step, the current state and available recovery
guidance. These alerts cover synchronous confirmation failures and background
BLAST, alignment, instrument-import and report jobs.

An independent database monitor checks queued assistant actions even when
Celery workers or Redis are unavailable. It detects:

- A job still waiting for a worker after the configured queue timeout.
- A running job that has not published another checkpoint within the progress
  timeout.
- A native job that already completed or failed while its assistant callback
  was missed; the monitor reconciles the assistant receipt with that real state.

A stalled warning means **no recent recorded progress**, not proof that a job is
dead. It never changes a scientific job to failed, stops an instrument or starts
another attempt. Checkpoints come from actual work: query/alignment FASTA
preparation, committed import-row progress and report processing. Older attempts
without recorded checkpoints explicitly say that no completed step was recorded.

Prepared instrument imports commit their data atomically. They publish a worker
checkpoint before the import transaction, and retain its last completed step
until the data transaction commits. Per-row action locks are avoided inside that
transaction, allowing the monitor to inspect a long-running import without
weakening import atomicity or claiming that uncommitted measurements were saved.

## Recovery in the interface

Open the notification or its **Review task in assistant** link to see the task
status directly in chat. **Refresh task status** reads the existing receipt.
Queued tasks displayed in chat refresh while they remain queued. Notification
history does not start a separate poller for every old alert; refresh is explicit.

**Review job** opens the exact BLAST/alignment job, including a record older than
the current list page. **Review import receipt** opens the existing import detail
page. Use rejected-row repair/revalidation and the normal preview/confirmation
controls when correcting instrument data. A fresh attempt still requires a new
confirmed proposal; there is no automatic retry that could duplicate data.

Progress or completion resolves a previous stall alert. A later real failure may
produce a separate failure alert; these describe different states. Each attempt
receives at most one stalled warning and one failure notification. Repeated
workers, concurrent monitors, marking a notification read or deleting it do not
recreate the same notice. Native failure notices for assistant-managed jobs are
consolidated into the enriched alert. Standalone jobs retain their existing
notifications, and completion notices remain available.

Notifications and status endpoints are scoped to the requester, including for
other administrators. Source-record access is checked before returning detailed
checkpoints, results or job links. If access is revoked, an active requester may
still receive a generic failure notice without private source details. Detailed
stall warnings are suppressed when source access is lost. Disabled accounts do not receive new
job alerts. Status views handle lost access or an unavailable server without
starting another action. English and Spanish controls are available.

## Deploy the independent monitor

This release includes **assistant.0011_job_progress_and_alerts** and
**assistant.0012_job_health_queue_index**, which supports the bounded status/ID
monitor scans. Apply migrations
before serving the new API/worker code. Rebuild all services from the same
checkout and include the new **assistant-monitor** service:

```bash
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml up -d --build api worker web assistant-monitor
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml logs --tail=80 assistant-monitor
```

Use your installation's existing project name and environment file. Production
Compose waits for the migrated API to become healthy before starting the monitor.
The worker checks migration readiness before consuming tasks, so an upgrade cannot
start the new progress hooks against an older database schema. Its restart policy
retries startup until the API's migration step finishes.
The monitor itself uses the database directly and does not require a Celery
worker or Redis to deliver an in-app alert. There is no new Python/JavaScript
package or email/SMTP requirement.

Defaults, configurable in the backend environment:

```dotenv
ASSISTANT_QUEUE_STALL_SECONDS=600
ASSISTANT_PROGRESS_STALL_SECONDS=1800
```

Choose an appropriate progress timeout for legitimate long scientific jobs.
The continuous monitor runs one bounded pass every 60 seconds and advances a
cursor between batches so previously alerted jobs cannot starve later jobs.
Its default batch is 500; `--batch-size` supports 1–5000 jobs per pass.

For non-Compose installations, supervise this command independently of Celery:

```bash
python manage.py monitor_assistant_actions --interval 60
```

For a single diagnostic batch:

```bash
python manage.py monitor_assistant_actions --batch-size 500
```

Database/schema outages are reported in the monitor log and retried by the
continuous command. SIGTERM/SIGINT stop the loop cleanly. Full deployment is
needed for unattended detection; simply updating the frontend does not start a
monitor. Check footer **0.75.0** after refreshing the browser. Both READMEs retain
exactly the three latest releases: 0.75.0, 0.74.0 and 0.73.2.

## Read-only API additions

```http
GET /api/v1/events/123/comparison/
GET /api/v1/assistant/jobs/<action-uuid>/
```

The event response contains `field_changes` and, when applicable,
`revision_comparison`. Audit list entries also expose `field_changes` and
`can_compare_revision`, without name-lookup queries per row. The assistant
response contains the existing action receipt plus `health` with checkpoints,
progress, stall state and recovery links. Existing `/api/` aliases also work.
These endpoints never confirm or rerun an action.

Backend tests exercise real PostgreSQL authorization, snapshot provenance,
immutable comparisons, worker redelivery, failure consolidation, report replay,
source-access changes, monitor batching and concurrent monitor/completion paths.
Browser tests use controlled API responses with the real application to verify
highlighting, escaped HTML, native notebook comparison, error handling, direct
job recovery, optional-module outages, notification polling and Spanish controls.
