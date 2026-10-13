# Questions across project samples (v0.46.0)

Ask about several samples together in the Assistant page or floating widget:

- `Which samples in project DEMO-360 are blocked, and why?`
- `Which samples in DEMO-360 are missing results?`
- `Which samples in project DEMO-360 need QC?`
- `Which samples in project DEMO-360 are ready?`
- `Which samples in project DEMO-360 failed QC?`
- `Which samples in project DEMO-360 are overdue?`
- `Which samples in project DEMO-360 are unassigned?`
- `Show samples in project DEMO-360 workflow overview`
- `¿Qué muestras en proyecto DEMO-360 están bloqueadas y por qué?`
- `¿Qué muestras en proyecto DEMO-360 tienen campos faltantes?`
- `¿Qué muestras en proyecto DEMO-360 necesitan QC?`

Use an exact project **code**, not a name or approximate spelling. Multiple project references ask for a single choice. The table links each sample and shows its pipeline run, step, reason and recorded work assignee where available. Assignees are not inferred to be QC reviewers. Reasons are prioritized within each sample, with recorded failures and QC gates before routine dependencies. Each reason has a suggested next action; overdue work shows its recorded due date. No suggested action is executed.

After selecting a project, `Which are ready?`, `Which are missing results?`, or `And QC?` switches the filter and refreshes the first page. `Only failed QC`, `Only overdue`, `Only unassigned`, `Solo QC rechazado`, `Solo vencidas` and `Solo sin asignar` also **replace** the current filters. `Refresh results` / `Actualizar resultados` rereads the current filters from the first page. `Next page` / `Siguiente página` continues the same query. A full question naming a different project switches projects. The context bar shows the selected project and filters; Clear or `Start over` removes them. Questions about an individual sample still use the existing sample-guidance route.

## Combined conditions and refinement

- `Which samples in project DEMO-360 are overdue and unassigned?` requires both conditions.
- `Which samples in project DEMO-360 failed QC or are missing results?` requires either condition.
- `¿Qué muestras en proyecto DEMO-360 están vencidas y sin asignar?`
- `¿Qué muestras en proyecto DEMO-360 tienen QC rechazado o campos faltantes?`
- After an AND or single-filter query, `Also unassigned`, `And only unassigned`, or `También sin asignar` adds an AND condition and restarts at page one.
- `Only unassigned` replaces the full query, whereas `Also unassigned` narrows it.

By default, conditions apply **per sample** and may be satisfied by different active steps or runs. They do not promise that the same work item satisfies every condition. Answers explicitly state this distinction and show the matching step evidence without duplicates. The context bar and table caption spell out AND/OR (Y/O in Spanish) and the scope, including a retained context label when no rows match.

The grammar is intentionally bounded: use the supported filters with explicit AND or OR connectors. Mixed AND/OR, parentheses, negation and arbitrary date/threshold constraints require clarification, rather than silently returning a broader answer. Refining an OR expression also asks for a fresh full query; nested expressions are not inferred. An unclear follow-up can retain a validated, accessible previous query; explicit new project questions and invalid context clear it. Existing exact-code access checks, scan limits, live pagination and read-only behavior still apply. This is not unrestricted natural-language reasoning or a new model integration.

## Same-step scope

- `Which samples in project DEMO-360 are overdue and unassigned on the same step?`
- `¿Qué muestras en proyecto DEMO-360 están vencidas y sin asignar en el mismo paso?`
- After a filtered project query: `On the same step` / `En el mismo paso` narrows its scope.
- `Across the sample` / `En toda la muestra` restores sample-level matching.

Same-step scope evaluates each step **within its own pipeline run**. Step 1 in one run cannot supply a condition for step 1 in another run. AND requires all filters on one step; OR requires at least one. Only reasons from qualifying steps are returned. Run-level blockers without a step are excluded. Workflow overview has no specific conditions, so combining it with same-step scope asks for clarification.

Scope changes restart at page one. Filter-only follow-ups (`Only unassigned`, `Also missing results`), refresh and pagination retain scope. A full question with an explicit project code starts from sample-level scope unless it explicitly requests same-step scope. Conflicting or malformed scopes ask for clarification. Older saved query contexts default to sample scope. The evidence table groups reasons by run/step and displays the linked work-item number; those numbers do not grant modification rights or execute actions.

## Meaning of the filters

| Filter | Meaning |
| --- | --- |
| Blocked | At least one recorded failure, unmet dependency, activation gate, missing/invalid required field, outstanding QC gate, or blocked run. This is an operational summary, not a change to sample status. |
| Missing results | Required results missing, empty or using the wrong type, plus required form fields identified by pipeline validation. |
| QC | Completed work awaiting required QC, including rejected/re-run review states. Pending work is not automatically treated as ready for QC. |
| Failed QC | Required work-item QC gates marked REJECTED or RERUN_REQUIRED; excludes pending reviews. This is work-item gate status, not individual result-level QC. |
| Overdue | Ready/in-progress steps with active work whose recorded due date has passed and whose dependencies are satisfied. |
| Due today/tomorrow/within 7 days | Available active work on ready/in-progress steps with satisfied dependencies and a recorded deadline inside the explicit window. See deadline rules below. |
| Assigned | One exact active project username or the authenticated user; unfinished steps with non-cancelled work, including work awaiting QC. |
| Unassigned | Ready/in-progress steps with active work, satisfied dependencies and no assignee. Not-yet-created blocked work is not counted. |
| Ready | A ready/in-progress step has its required fields, satisfied dependencies and active work awaiting review. Review and complete that work through the existing controls. This does **not** mean the sample is QC-approved or sequencing-ready. |
| Workflow overview | Current step evidence for all samples on the page, including samples with no active pipeline. |

A sample can have available work in one branch and a blocked step in another. Ordinary downstream dependencies count as blockers but do not prove the whole sample is stalled. Completed, skipped and cancelled steps and historical runs do not supply current blockers. Samples marked REPORTED, CANCELLED or ARCHIVED are excluded.

## Access, paging and freshness

Only project members or admins can query the project. Samples belong through either their primary project or a linked project and still pass the sample access filter. Viewer members can read; linked membership does not grant editing. Every question and next-page request rechecks membership. Access denial clears the retained project context.

Each response returns up to **25 matching samples** in database-ID order. It scans past nonmatches in batches of 25, checking at most **250 samples per request**. Counts distinguish matches shown, samples checked, accessible non-final project scope, and samples remaining to check. A complete project match count is provided only when that request starts at the beginning and reaches the end; otherwise it remains unknown. Counts are never accumulated from client context.

When the scan limit is reached, the response says so and offers Next page even when no matches were found. The cursor resumes after the last sample actually checked, so unread candidates in a prefetched batch are not skipped. Up to six prioritized matching reasons per sample are shown, with a count and link for additional reasons. Use Refresh results to start again. Pages are live rather than a frozen report; concurrent changes may affect results and counts.

These queries are read-only, use batched ORM retrieval, and work without a provider. They bypass external-model interpretation and rewriting; OpenAI/Ollama do not directly query the database. A project summary does not select samples for bulk writes or create a confirmation action. There is no unrestricted SQL or semantic search in this feature.

## Verification

`backend/assistant/tests/test_project_workflows.py` covers project/sample permissions, linked samples, viewers, revocation, forged context, pagination across scan batches, scan caps, exact versus partial counts, failed-QC/overdue/unassigned filters, combined AND/OR, refinement versus replacement, refresh, current QC/field evidence, excluded historical records, Spanish input, ambiguity, provider bypass, no mutation and bounded query counts as sample counts grow. `test_workflow_query.py` checks the bounded grammar and malformed context. `frontend/scripts/assistant-workflow-context.test.mjs` checks interpreted filter labels and compatibility with older messages.

```bash
cd backend
CELERY_BROKER_URL=memory:// CELERY_RESULT_BACKEND=cache+memory:// python -m pytest assistant/tests --nomigrations -q
```

No database migration is needed.

### Edit a combined question

After asking about `overdue and unassigned` samples, use:

- `Match any condition` / `Cumplir cualquier condición` to use OR.
- `Require all conditions` / `Cumplir todas las condiciones` to use AND.
- `Remove the overdue filter` / `Quitar el filtro de vencidas` to keep only the other filters.

These follow-ups preserve the project and sample/same-step scope, restart at page
one, and reread live records with current permissions. Combined answers suggest
the opposite match mode. Removing a filter does not negate it: samples meeting
the removed condition may still appear. At least one active filter must remain;
unknown filters, unsupported constraints, and invalid context ask for clarification.
No lab records are changed. These exact, bounded commands work without an external
AI provider.

### Recover from an unclear follow-up

If an edit or follow-up cannot be interpreted, the assistant explains the issue
and retains the previous valid query when its project is still accessible. For
example, after an `overdue OR unassigned` question, `Also missing results` needs
clarification because it would mix AND and OR. The assistant does not apply that
change or return new results. It shows the previous filters and scope, with
English/Spanish choices to refresh, switch matching mode, remove an active
filter, or start over.

Recovery resets the cursor, discards extra client context, and checks project
access. Selecting a choice rereads current records and permissions. Invalid
prior filters/scopes, revoked access, and explicit new project questions do not
retain the old query. Removing a filter relaxes a query; it never means excluding
samples with that condition. Recovery suggestions refer to the previous query,
not to the rejected edit.

### Understand an empty result

An empty answer reports per-condition sample counts from the current scan using
the requested scope. Counts overlap; never add them. If same-step scope finds no
matches but whole-sample scope would, the answer reports that measured difference
and offers `Across the sample`. If individual conditions match an AND query, it
prioritizes `Match any condition`. These suggestions change the query only when
selected. `Next page` remains first when more candidates remain.

Diagnostics reuse current, permission-filtered evidence and add no database
queries. They exclude final and inaccessible samples. Missing active/blocked
pipeline runs are counted separately and do not imply completed work. Counts
cover the complete project only when one request scans the entire accessible,
non-final set. Later pages never accumulate earlier counts or claim a complete
project total. Responses with matches omit diagnostics (the structured field is
null); no client-provided diagnostic values are reused.


### Assigned work

- `Which samples in project DEMO-360 are assigned to me?`
- `Which samples in project DEMO-360 are assigned to maria and overdue on the same step?`
- `¿Qué muestras en proyecto DEMO-360 están asignadas a mí y vencidas en el mismo paso?`
- `Only assigned to maria` / `Solo asignadas a maria` replaces the filters.
- `Also assigned to me` / `También asignadas a mí` adds ownership to an AND query.
- `Remove the assigned to maria filter` / `Quitar el filtro de asignadas a maria` removes ownership if another filter remains.

Use one exact, case-sensitive username of an active project member, or `me` /
`mí` for the authenticated user. First names, approximate names, several owners,
negation and arbitrary date constraints are not resolved automatically. The canonical
username appears in query context and the evidence table. Unknown, inactive or
out-of-project users return the same unavailable response without user suggestions.

Assigned means a non-cancelled work item on an unfinished step of an active or
blocked run. This includes completed work awaiting a step's QC gate; it does not
mean the user can approve QC or that the work is ready. Terminal steps and runs
are excluded. Whole-sample AND can combine different steps/runs; choose same-step
scope when all conditions must describe that person's step. OR can include
samples matching another condition even if not assigned to that person.

Refresh, pagination, recovery and scope changes retain the username and recheck
current membership, activity, sample permissions and assignment evidence. Removing
or replacing the assigned filter clears the username from context. An explicit
new project query must specify its own assignee. Attempting to add a different
owner asks for clarification; use `Only assigned to ...` to replace it. These
read-only queries never create assignments, confirm actions, or call an external
provider. Scan limits and partial-count rules remain unchanged.


### Deadline questions

- `Which samples in project DEMO-360 are due today?`
- `Which samples in project DEMO-360 are assigned to me and due tomorrow on the same step?`
- `Which samples in project DEMO-360 are due in the next 7 days?`
- `¿Qué muestras en proyecto DEMO-360 están asignadas a mí y vencen mañana en el mismo paso?`
- `Also due today` / `También vencen hoy` adds a deadline to an AND query.
- `Only due within 7 days` / `Solo vencen en los próximos 7 días` replaces the filters.
- `Remove the due today filter` / `Quitar el filtro de vencen hoy` removes that condition if another remains.

Today/tomorrow mean calendar days in Django's active timezone (UTC in the default
configuration), not a timezone inferred from the browser or user message. Day
length follows daylight-saving changes. The next seven days mean exactly 168
hours from the request time, not seven midnight boundaries. Answers and structured
`deadline_windows` include exact start/end timestamps and timezone. Start is
inclusive and end is exclusive. Today may overlap overdue; the seven-day window
excludes past deadlines. `Due soon` is an alias for the same 168-hour window.

Only active PENDING/IN_PROGRESS work on READY/IN_PROGRESS steps with satisfied
dependencies matches these filters. No due date, completed/cancelled work,
terminal steps/runs or dependency-blocked work do not match. These filters describe
recorded deadlines, not expected completion or QC approval. Assignee and same-step
rules remain unchanged; OR may match a different condition.

A single server timestamp is used for all deadline and overdue comparisons within
a request. Every refresh/page recomputes relative windows; pages are live, not a
snapshot. Client-supplied window timestamps are ignored and are not retained in
query context. Partial scan counts and permission checks work as before. Explicit
other dates, timezones, times of day and custom day counts require clarification.

## Query explanations

After a project workflow question, choose **Explain this query** or type **Explica esta consulta**. Both chat views explain each filter, AND/OR matching, whether conditions may span steps or must match one step in one pipeline run, exact work ownership, and scan limits. The API also returns the complete plain-text answer and a `query_explanation` object.

Explanations recheck project access and active assignees, validate the saved query, and retain only supported context fields. Invalid or revoked context is cleared. They do not scan sample records, invoke a language model, or modify laboratory records. A valid page cursor is preserved: **Next page** continues; **Refresh results** restarts from page one with live data.

Relative deadline windows are resolved from the server clock at explanation time. They describe the query **if run now**, not the windows or counts of an earlier result. Today/tomorrow use the active Django timezone; next seven days means 168 hours. The start is inclusive and the end exclusive. Explanations distinguish work ownership from QC review and required-field readiness from QC approval.

## Build and reuse workflow questions

Open **Build a workflow question** in the assistant page or floating chat. Enter an exact project code, select conditions, choose AND/OR and same-step/sample scope, then inspect the question before clicking **Run question**. The builder supports English and Spanish and uses the same read-only, permission-checked rules as typed questions. Nothing runs while editing. **Load current query** fills the controls from the current workflow context; changing the project runs a new query from page one.

Quick starts select **My overdue work**, **Due soon, unassigned**, or **QC problems**. A work owner requires one exact username or `me` / `mí`. Workflow overview cannot be combined with other filters or same-step scope. The question preview explains validation problems before submission.

To reuse an existing question without opening the builder, type **Use the same filters in project SECOND** or **Usa los mismos filtros en proyecto SECOND**. This keeps the filters, AND/OR logic, scope and exact owner. It verifies the source query, source access, destination access and owner availability, resets pagination, and recalculates deadlines from the server clock. The response identifies both projects; subsequent pages and explanations belong to the destination. It does not compare projects or reuse old counts.

Use one exact destination code without extra conditions. An ambiguous command asks for clarification and retains the validated previous query, reset to page one. Invalid or revoked source context, inaccessible destinations and unavailable owners clear the workflow context without scanning samples. No laboratory records are modified and no language model is required.
