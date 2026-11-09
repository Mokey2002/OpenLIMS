# Access requests and administrator approvals

OpenLIMS v0.73.0 lets authenticated users request project membership or an
application role. Requests grant no access until a different administrator
approves them. This feature uses the existing project memberships, Django
groups, notifications and audit log.

## Request access

1. Open **Review → Access requests**, or **My profile → Access requests**.
2. Choose **Project membership** and enter the code supplied by your laboratory,
   or choose **Application role** and select viewer, technician or QC reviewer.
3. Provide a reason of 10–2,000 characters and submit.
4. Follow the request under **My requests**. Use the status filter to see past
   decisions, their reasons and reviewers. A pending request can be withdrawn.

Project codes are accepted without exposing whether the project exists. The
form does not list private projects, names or members. If the code is incorrect
or ambiguous, an administrator can reject the request with a clarification.
Submitting the same pending target again returns the original request and
reason; it does not send another notification. After rejection or withdrawal,
the user can submit a new request.

New accounts without application roles can use this page to request a baseline
role. Administrator access cannot be requested here. Administrators already have
full application access and use this page to review other users' requests.

## Review the queue

Administrators can open **Users → Review access requests** or the same Review
menu. The queue defaults to pending requests, with pagination and status filters.
A new request sends an in-app notification to active administrators. Email
configuration is not required.

Open **Review request** to see the requester, current roles, submitted reason
and, for project requests, the actual project name and code. Supply a decision
reason of 10–2,000 characters before approving or rejecting. Missing/ambiguous
projects and inactive/deleted accounts cannot receive grants, but their requests
can be rejected. Another administrator must review your own pending request if
you have since become an administrator.

A decision sends an in-app notification to the requester. Its link opens all
statuses so the completed request remains visible. Users can choose **Reload
account access** to refresh the navigation after a role changes.

## What approval changes

| Requested access | Result |
| --- | --- |
| Project membership | Adds the requester to that project's existing `members` relation. |
| Viewer (`viewer`) | Adds the existing read role. |
| Technician (`tech`) | Adds the existing technician role, subject to project and native action permissions. |
| QC reviewer (`qc_reviewer`) | Adds the existing QC review role; native QC restrictions remain in force. |

Project membership and application roles are separate requests. Membership does
not turn a viewer into a technician, and a role does not add private project
memberships. Role grants are additive and do not set `is_staff` or `is_superuser`.
Already assigned access is recorded as an approval with `access_changed=false`.

In **Users**, editing account details without changing the role selector keeps
all assigned roles. Deliberately changing the role selector uses the existing
replacement behavior. Existing administration controls still manage revocation;
an approval receipt is historical and is not a permanent access entitlement.

## Integrity and visibility

- Requesters see only their own requests and submitted target codes/roles.
  Only administrators can inspect the resolved project or review queue.
- Requests are immutable. Requester/status/target overrides and unknown fields
  are rejected. Use the dedicated review or withdrawal actions.
- A partial database uniqueness constraint and requester row lock allow one
  pending request per normalized target and account. Submissions are limited
  to 20 per account per hour.
- Approval locks the request, current reviewer/requester records and project;
  it checks current administrator privileges and requester activity again.
- Project approval must include the public UUID returned by the preview. A
  deleted/recreated project with the same code cannot reuse a stale preview.
  Refresh the preview and assess the newly resolved project before deciding.
- Grant, final decision, audit event and notifications share one transaction.
  A failed audit write rolls back the grant and leaves the request pending.
- Repeating the same final decision returns its stored receipt. It never
  regrants access removed later, sends another notification or writes another
  audit entry. A conflicting decision returns HTTP 409.
- Withdrawal is also repeat-safe and cannot cancel an already reviewed request.
- Audit actions are `ACCESS_REQUEST_SUBMITTED`, `ACCESS_REQUEST_APPROVED`,
  `ACCESS_REQUEST_REJECTED` and `ACCESS_REQUEST_CANCELLED`, on `AccessRequest`.
  Their visibility follows the requester/admin policy and existing audit project
  snapshot restrictions. Unrelated users cannot read their reasons through the
  audit feed. Django admin exposes requests read-only.

## API

Use the normal Bearer JWT or browser cookie/CSRF authentication. Both `/api/v1/`
and compatibility `/api/` routes are supported. Examples are JSON bodies, with
the authenticated user acting as requester or administrator as appropriate.

```http
POST /api/v1/access-requests/
Content-Type: application/json

{"kind":"PROJECT","project_code":"ALPHA","reason":"I am joining the sequencing team"}
```

For a role, send `{"kind":"ROLE","role":"tech","reason":"I will process laboratory samples"}`.
A new request returns 201; a repeat pending submission returns 200 and the same
UUID. Requesters cannot supply another user or a preapproved status.

| Endpoint | Purpose |
| --- | --- |
| `GET /access-requests/` | Own requests, or all for administrators; `status`, `page`, `page_size`; admins may use `mine=1`. |
| `GET /access-requests/{id}/` | Request receipt/history within the same scope. |
| `GET /access-requests/{id}/preview/` | Admin-only resolved target, blockers and approval eligibility. |
| `POST /access-requests/{id}/review/` | Admin-only approval/rejection with a reason. |
| `POST /access-requests/{id}/withdraw/` | Requester-only withdrawal; send `{}`. |

Review body, using the project's UUID from the preview:

```json
{
  "decision": "APPROVED",
  "decision_reason": "Confirmed project duties with the laboratory manager",
  "project_public_id": "UUID-FROM-PREVIEW"
}
```

Use `REJECTED` to decline. Role approvals and rejections do not require
`project_public_id`. Inspect `can_review`, `can_withdraw` and preview `blockers`
for UI guidance; the server always rechecks authorization when executing.

## Upgrade and verification

This release adds **`core.0003_access_requests`**. Back up the database using
your existing procedure, rebuild/recreate the API and web images from the same
checkout and apply migrations before serving API traffic. The production Compose
API startup already runs `migrate --noinput` before starting Daphne:

```bash
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml up -d --build api web
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml logs --tail=80 api
```

Use your installation's existing project name, Compose file and environment.
Custom deployments that do not run migrations on startup must run
`python manage.py migrate --noinput` in the updated API environment first.
No new dependency, worker job, email service or feature flag is required. Refresh
the browser and check that its footer reads **0.73.0**.

Backend regressions exercise real PostgreSQL-backed API views, native project
and sample permissions, cookie/CSRF authentication, invalid payloads, privacy,
offboarding/demotion, stale project identity, transaction rollback, retries and
simultaneous submissions/decisions:

```bash
docker compose -f deploy/docker-compose.yml exec -T api pytest -q core/tests/test_access_requests.py core/tests/test_access_request_concurrency.py
```

The PostgreSQL concurrency tests skip on other databases; set
`REQUIRE_POSTGRES_TESTS=1` to require those locks in CI. Browser tests in
`frontend/e2e/tests/access-requests.spec.js` use mocked API responses with the
real UI to check request/review/withdrawal, replay feedback, stale previews,
pagination, notification-link filters, Spanish and preservation of added roles.
