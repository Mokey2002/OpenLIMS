# Assistant Phases 3–5

OpenLIMS Phases 3–5 use deterministic, permission-filtered tools. Read-only
questions run immediately. Every write is stored as an `AssistantAction`, shows
an exact preview, expires after 15 minutes, and runs only after the requesting
user explicitly confirms it.

## Phase 3: controlled bulk sample operations

Supported examples:

- `Move all received samples in Project Alpha to PROCESSING.`
- `Add samples S-100 through S-120 to batch B-100.`
- `Archive cancelled samples older than 90 days.`
- `Assign all unassigned samples in this batch to Maria.`

The preview freezes exact database IDs and current state snapshots. Execution
uses that frozen set, revalidates permissions, required custom fields, workflow
transitions, and record state, and reports individual failures. The default
limit is 100 records and can be changed with
`OPENLIMS_ASSISTANT_BULK_MAX_RECORDS`.

## Phase 4: QC review workflow

Read-only examples:

- `Show results that failed QC this week.`
- `Which results are awaiting approval?`
- `Why did result R-204 fail QC?`
- `Compare result R-204 with its reference range.`

Confirmed action examples:

- `Flag result R-204 for review.`
- `Assign failed QC results to Maria.`
- `Reject result R-204 because the control failed.`
- `Approve results 301 through 305 because the controls passed.`
- `Reopen result R-204 because a new control was run.`

Approval, rejection, and reopening require the `qc_reviewer` or `admin` role
and an explicit reason. When `qc_separation_of_duties` is enabled, a user cannot
approve a result they entered. Approved or rejected results must be explicitly
reopened before another review decision. Every decision records the actor,
timestamp, reason, and before/after state. Automated QC can explain and warn,
but it never makes the approval decision.

## Phase 5: inventory and sample locations

Read-only examples:

- `Which reagents expire in the next 30 days?`
- `Show inventory below its reorder level.`
- `Where is sample S-1042?`
- `Who last moved sample S-1042?`
- `What is stored in freezer F2, rack R4?`

Confirmed action examples:

- `Move sample S-1042 to freezer F2, rack R4, box B3.`
- `Reserve two units of reagent R-100 for Project Alpha.`
- `Record consumption of 50 mL from lot L-204.`
- `Mark lot L-204 as expired.`

Containers support validated freezer/location, rack, and box hierarchy.
Inventory lots enforce nonnegative quantity. Volume, mass, and count units are
converted only within compatible dimensions. Reservations revalidate project
access and available quantity at confirmation. Sample moves emit
`SAMPLE_MOVED` chain-of-custody events; reservation, consumption, and expiration
write inventory audit events with before/after values.

## Upgrade

After deploying the code:

```bash
python manage.py migrate
python manage.py init_roles
```

Assign authorized reviewers to the `qc_reviewer` group. Administrators can
enable QC separation of duties from Admin Settings.
