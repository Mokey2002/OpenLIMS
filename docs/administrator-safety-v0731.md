# Last active administrator protection

OpenLIMS v0.73.1 prevents supported account-management operations from removing
the last active application administrator. An administrator is an account with
`is_active=True` and either Django `is_superuser=True` or membership in the
`admin` group. One account counts once even if it has both grants. Inactive
administrators and accounts with only `is_staff=True` do not count as backups.

## Administrator handover

1. Create or activate another administrator in **Users**.
2. Confirm that the other administrator can sign in and manage users. Invitation
   delivery and password setup remain separate from the account's active flag.
3. Disable, delete or change the old administrator's role as appropriate.

The Users page marks the last administrator and disables its Disable, Delete,
role selector and active-status switch. Name/email edits and saving the existing
administrator role remain available. Extra roles remain intact when the role
selector is unchanged. The status switch has an associated accessible label.

A stale page may still offer an action that is no longer allowed. The server
rejects it, the list refreshes, the protected controls update, and a message
explains how to preserve administrator access. A rejected role edit closes the
edit form. A denied write after administrator revocation removes the management
controls from the page. English and Spanish messages are provided.

## Protected paths

| Entry point | Protection |
| --- | --- |
| `PATCH` or `PUT /api/v1/admin-users/{id}/` | Rejects deactivation or a role change that would remove the last administrator. |
| `DELETE /api/v1/admin-users/{id}/` | Rejects removal of the last administrator. |
| Compatibility `/api/admin-users/` | Uses the same backend checks. |
| Django user administration | Checks active/superuser/group changes and both single and bulk deletion. Password changes use the same account transaction ordering. |
| Django group administration | Checks renaming or deleting `admin`, including bulk deletion, when no active superuser would remain. |
| Migration rollback | Rejects user deletion or restoration of old flags/groups that would remove the final administrator; rolls back the whole attempted rollback. |

User list/detail API responses include the read-only `is_last_active_admin` flag
for interface guidance. The user API rejects a conflicting write with HTTP 409:

```json
{
  "detail": "Keep at least one active administrator. Create or activate another administrator before removing this access.",
  "code": "last_active_administrator"
}
```

Django admin renders a form error or protected deletion preview. Migration
rollback retains its existing HTTP 409 validation response with the same
explanation. Ordinary users and administrators with an active backup can still
be managed normally under the existing permissions.

## Concurrency and audit

A dedicated singleton database row serializes account and administrator-group
changes. The lock and mutation share one transaction; a count taken only before
locking would let simultaneous requests remove both remaining administrators.
Actor/target User records are locked in ascending order, matching access-request
review ordering. Waiting requests recheck current administrator privileges.
Django admin also refreshes the actor's account before proceeding with its
normal permission checks.

API account changes and deletions now commit with their audit event. A failed
audit write rolls back the role/account change. A safety rejection changes no
account, membership or successful-change audit record. Django admin keeps its
existing administrative log. Existing audit records are preserved.

The safeguard applies to these application workflows. Privileged direct SQL,
custom scripts and maintenance commands bypass application-level checks. The
rule preserves an active administrator account; it does not verify that another
person knows that account's credentials, which is why a handover includes a
sign-in check.

## Upgrade and checks

Apply **`core.0004_user_administration_lock`**, rebuild/recreate **api** and
**web** from the same checkout, and refresh the browser. The internal lock row
is created on first use. Production Compose runs migrations before starting
the API:

```bash
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml up -d --build api web
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml logs --tail=80 api
```

Keep your installation's existing Compose project name and environment file.
Custom API startup commands must apply migrations before serving requests.
The footer reads **0.73.1**. No new dependency or environment variable is needed.
Both READMEs retain only **0.73.1, 0.73.0 and 0.72.6** release updates.

Backend tests exercise the native user API, Django user/group forms and deletion
actions, migration rollback, audit failure, ordinary profile edits and valid
handovers. PostgreSQL tests race administrator deactivation, deletion and
demotion; CI sets `REQUIRE_POSTGRES_TESTS=1` to prevent silent skips on a database
without the required locking behavior.

```bash
docker compose -f deploy/docker-compose.yml exec -T api pytest -q core/tests/test_user_safety.py core/tests/test_user_safety_concurrency.py
```

`frontend/e2e/tests/administrator-safety.spec.js` uses mocked API responses with
the real UI to exercise disabled controls, permitted profile edits/handovers,
stale-page conflicts, lost administrator access and Spanish messages. Backend
API and Django admin tests use a real PostgreSQL test database.
