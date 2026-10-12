# Questions across project samples (v0.43.0)

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

The grammar is intentionally bounded: use the supported filters with explicit AND or OR connectors. Mixed AND/OR, parentheses, negation and assignee/date/threshold constraints require clarification, rather than silently returning a broader answer. Refining an OR expression also asks for a fresh full query; nested expressions are not inferred. Clarification clears the old context, so repeat the project code. Existing exact-code access checks, scan limits, live pagination and read-only behavior still apply. This is not unrestricted natural-language reasoning or a new model integration.

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
