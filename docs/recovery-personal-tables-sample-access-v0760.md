# Draft recovery, personal tables and sample visibility — v0.76.0

## Recover unfinished notebook work

Notebook entry blocks and linked records are copied to browser session storage
as soon as they are edited, before the autosave delay. Copies are separate for
each account and experiment in the current tab. They survive a refresh, a
failed save or navigating away and returning. This is a recovery aid for the
current browser tab, not a server backup or offline authorization mechanism.
Closing the tab/browser may remove session storage. Copies expire after seven
days, and copies larger than 2 MiB are not stored. Storage failures show a warning
to keep the page open until the server confirms a save.

On reopening an accessible experiment, **Review recovered draft** compares the
current saved content with the recovery copy. Restoring only puts the draft into
the editor; use **Save now** to commit it. If a collaborator has saved a newer
revision, explicitly acknowledge the comparison before restoring. The next save
still supplies the expected current revision, so another intervening edit is
rejected by the existing server conflict check. Reviewed/locked experiments allow
review/download of a recovery copy but cannot restore it for editing.

Successful saves clear the corresponding copy only when no newer local edits
exist. Slow saves run in order; edits made during a save keep their recovery
copy and use the confirmed revision for the next save. If a save succeeded but
its response was lost, reopening identical saved content clears the redundant
copy without creating another revision. Failed saves retain the editor and offer
**Retry saving edits** or **Review latest saved version**. Reviewing the latest
version preserves the recovery copy instead of overwriting the server.

Internal navigation and browser back/forward warn about unsaved entry changes.
Refresh, closing the tab and external navigation use the browser's native warning.
Signing out asks before discarding the open editor. Recovery is offered only
after fresh authenticated experiment access succeeds; another account cannot
recover the previous user's copy. A copy does not grant access to a revoked
notebook. Other unsaved metadata forms and attachment uploads are not included
in the notebook entry recovery copy.

## Personal table views

**Samples**, the **Work Queue**, and Inventory's items, lots, reservations,
locations, containers and ledger remember presentation settings per account,
table and browser. Settings include search, sorting, visible columns, page size
and page number. Work Queue also remembers type/status filters; Samples remembers
status/project/container filters. Opening a sample and using Back restores its
list view and scroll position. Scroll positions are scoped to the account and
current tab. An explicit project link overrides a different remembered project
filter while returning to the same project preserves the page.

Use **Visible columns** to simplify a table or **Reset table view** to return to
the default display. Sample identity and essential row actions remain available.
Selections for bulk changes and partially filled action forms are not remembered.
Stored display settings do not copy laboratory data, change memberships or bypass
API authorization. They stay in this browser and do not synchronize devices.
Blocked browser storage leaves the current page usable without persistence.

Sample sorting runs on the server before pagination. Only sample ID, status and
creation time are supported, in either direction, with a stable ID tie-breaker.
An invalid remembered page resets to page one. Inventory and work tables filter,
sort and paginate the API-authorized rows already loaded by those pages. Empty
filtered tables retain settings controls, so their filters can be cleared.

## Sample visibility rule

Every authenticated, active account, including administrators, can read a sample
when **either**:

- The user belongs to its primary project or at least one linked project.
- The sample has no primary project **and no linked projects**.

Missing only the primary project does not make a sample public if it still has
linked projects. Creating a sample or being assigned to it does not grant access
to another project's data. Multiple matching memberships do not duplicate rows.
Administrators who need to see a project's samples must join that project through
the existing project membership controls.

The common predicate governs sample lists, individual records, scoped history,
search, exports, related work/results, shared entity resolution and assistant
sample queries. Administrative sample-related audit reads and project report
metrics also apply the sample rule. An inaccessible sample returns 404 on record
routes, and filtering/counts apply authorization before pagination.
Sample-related audit records whose target no longer exists are not granted
access from an unverified historical identifier; unrelated administrative audit
records retain their existing administrator visibility.

Visibility does not add write permissions. Viewers remain read-only; membership
only in an additional linked project still grants read access. Existing technician
ownership rules and administrator write capabilities continue for visible records.
An unassigned sample created by somebody else is visible without granting a
technician permission to edit it. No historical records or memberships are changed
by the upgrade.

The operation scope for work items, results, attachments and QC stays separate
from public read access, including assistant previews and confirmation. Creating
or reassigning a work/result/attachment parent checks that operation scope too.
Work Queue marks rows that the current account cannot update as **Read-only**.

## Upgrade and validation

Rebuild/recreate API, worker and web from the same checkout. This release adds no
database migration or dependency. Keep the independent assistant monitor from
v0.75.0 running. Confirm footer **0.76.0** after refreshing. The English and Spanish
READMEs retain exactly the latest three releases: **0.76.0, 0.75.0 and 0.74.0**.

Backend tests use PostgreSQL to check visibility, direct links, revocation,
ordering, pagination, exports, search, audits and unchanged write boundaries.
Browser tests exercise failed-save recovery, conflict acknowledgement, navigation
warnings, serialization of slow saves, account isolation, locked/revoked records,
unavailable storage and returning to remembered Samples/Inventory/Work Queue
views. Their API responses are controlled; server permissions are tested separately.
