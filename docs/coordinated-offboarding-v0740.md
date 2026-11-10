# Coordinated account offboarding (v0.74.0)

Administrators can open **Users → Offboard** to review and complete a laboratory
handover in one place. Ordinary **Disable** remains available for a temporary
account suspension; coordinated offboarding also removes access, transfers
responsibilities and permanently revokes existing sessions.

## Administrator workflow

1. Open the departing person's **Offboard** action, including accounts already
   disabled. Self-offboarding and the last active administrator are protected.
2. Expand the responsibility categories to inspect record names and states.
3. Choose an active replacement and give a reason of at least 10 characters.
   If the person has no outstanding responsibilities, a replacement is optional.
4. Verify any physical sample handoff and explicitly acknowledge it. The system
   records a custody transfer; it does not infer that a physical handoff occurred.
5. Prepare the 15-minute preview and inspect the transfers and access removal.
6. Acknowledge the preview and confirm. Keep the same preview when retrying a
   missing response; the server returns its receipt without repeating changes.

The replacement must already have the appropriate technician/QC role and access
to the relevant projects and notebooks. Notebook and registry ownership changes
are explicitly listed and grant ownership of those records. No application roles
or general project memberships are copied. QC separation follows the laboratory's
configured policy; pending registry reviews require an independent replacement.
Unassigned samples require a replacement with existing sample access (normally an
administrator); assigning the sample to a suitable project first is another option.

## Responsibility coverage

| Responsibility | Handover behavior |
| --- | --- |
| Samples assigned in RECEIVED, IN_PROGRESS or QC | Transfer the operational assignment. |
| Physical sample custody, in any state | Record a TRANSFER custody event after verified handoff; preserve storage placement. |
| PENDING, IN_PROGRESS or FAILED work items | Transfer the assignee; preserve work status and original creator. |
| Results awaiting QC (PENDING_REVIEW or REOPENED) | Transfer the QC assignment to an eligible reviewer. |
| Notebook ownership | Transfer the owner, preserving scope, project, content and permissions for other collaborators. |
| DRAFT, IN_PROGRESS or COMPLETED experiment assignments | Replace the departing assignee; keep other assignees. |
| Pending workflow steps in draft/in-progress experiments | Transfer the assignee and advance the step version so stale step forms cannot overwrite the handover. |
| Unresolved assigned notebook comments | Transfer the task assignment; preserve the author's text. |
| Registry ownership | Transfer the owner without changing scientific versions or lifecycle state. |
| Pending assigned registry reviews | Transfer the reviewer, preserving request authorship. |

Completed workflow steps, historical work assignments, approved results, review
signatures, notebook revisions, creators, submitters and audit actors retain
their original attribution. Open workflow requests and future instrument bookings
authored by the departing person remain visible in the review. Already queued
assistant jobs are listed as continuing work. Offboarding does not kill external
processes, stop sequencers, cancel submitted requests or cancel bookings. Use their
existing controls when cancellation is needed; the handover does not rewrite authorship
to make an existing job appear to have been requested by the replacement.

## Access and sessions

One transaction transfers the reviewed responsibilities, removes all project
memberships and explicit notebook/team grants, clears account groups and direct
permissions, clears staff/superuser flags, and disables the account. It also:

- Cancels pending access requests with an audited decision.
- Cancels unconfirmed assistant proposals and asks running chat requests to stop.
- Disables notification subscriptions addressed to the departing account.
- Blacklists outstanding, unexpired refresh tokens and removes Django database
  sessions for that user.
- Advances a persistent session generation, invalidating old access and refresh
  credentials, including cookies and legacy bearer tokens. Unaffected users keep
  their existing credentials; no backfill or forced system-wide logout is needed.
- Closes the user's job-update WebSockets after commit. Each outbound job update
  and incoming socket message also checks the credential, covering a missed
  channel-layer close notification.
- Records one account offboarding event and the individual domain transfers,
  and notifies the replacement inside OpenLIMS.

The full administrative departure reason stays in the administrator-only plan,
receipt and account audit. Shared scientific-record history, custody events and
recipient notifications use the operational handover reason instead. Each
transfer shows the specific responsibility and previous/replacement assignees.

Reactivation does not restore removed roles/memberships or make old tokens valid.
Grant the required access explicitly and sign in again. This workflow does not
change the user's password or delete their scientific data.

## Consistency and recovery

Previews are stored server-side and bound to the preparing administrator, account,
replacement and reason. Confirmation accepts only the preview ID and explicit
acknowledgment. It rechecks the administrator, replacement, required access,
responsibilities, policy and preview expiry under account/domain transaction locks.
A changed snapshot returns HTTP 409 and requires a new preview. Account administration
and access-request decisions share their lock order. Mutually attempted administrator
offboardings cannot remove all administrators.

If a transfer, audit write or other database operation fails, the transaction
rolls back all changes, including session generation and the receipt. Concurrent
confirmation of the same preview returns the same completed receipt. Replaying
an old completed receipt after reactivation returns that history without
disabling the account again. Previously completed receipts are available when
reopening the review. A network failure or gateway error keeps the confirmation
available for retry, without allowing its parameters to be edited in place.

## API

Both the versioned routes below and their existing `/api/` aliases are supported.
All endpoints require a current active administrator. Cookie mutations require CSRF.

```http
GET /api/v1/admin-users/42/offboarding/
```

```http
POST /api/v1/admin-users/42/offboarding/preview/
Content-Type: application/json

{
  "successor_id": 51,
  "reason": "Reviewed laboratory departure and handover",
  "custody_confirmed": true
}
```

Use `custody_confirmed: true` only after verifying a physical handoff when custody
records are present. Preparing a preview makes no business changes. HTTP 201
returns `preview_id`, expiry, the reviewed snapshot, replacement and reason.

```http
POST /api/v1/admin-users/42/offboarding/confirm/
Content-Type: application/json

{
  "preview_id": "<the returned UUID>",
  "confirmed": true
}
```

HTTP 200 returns the stored completion receipt and counts. Unknown fields are
rejected. A different administrator cannot reuse the preview. Expired or changed
previews return 409; ineligible replacements return validation blockers.

## Deployment and verification

Apply **core.0005_coordinated_offboarding** before serving requests with the new
API/worker code. Rebuild API, worker and web from the same checkout. Production
Compose runs migrations before starting the API:

```bash
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml up -d --build api worker web
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml logs --tail=80 api
```

Use your deployment's existing project name and environment file. No new package
is required. Refresh the browser and check footer **0.74.0**. The English and
Spanish READMEs keep exactly the three latest releases: 0.74.0, 0.73.2 and 0.73.1.

Backend tests cover real PostgreSQL transfers, eligibility and access checks,
stale/expired previews, immutable authorship, rollback, receipt replay, concurrent
confirmations, administrator protection, authentication/refresh/reactivation and
open WebSocket revocation. Browser checks exercise the real Users UI using
controlled API responses: review, verified custody, blockers, explicit confirmation,
stale previews, permission revocation, network/gateway recovery and Spanish.

```bash
docker compose -f deploy/docker-compose.yml exec -T api pytest -q core/tests/test_offboarding.py core/tests/test_offboarding_concurrency.py core/tests/test_offboarding_sockets.py
```
