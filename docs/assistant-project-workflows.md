# Questions across project samples (v0.41.1)

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

After selecting a project, `Which are ready?`, `Which are missing results?`, or `And QC?` switches the filter and refreshes the first page. `Only failed QC`, `Only overdue`, `Only unassigned`, `Solo QC rechazado`, `Solo vencidas` and `Solo sin asignar` also switch filters. These are replacements, not combinations. `Refresh results` / `Actualizar resultados` rereads the current filter from the first page. `Next page` / `Siguiente página` continues the same filter. A full question naming a different project switches projects. The context bar shows the selected project and filter; Clear or `Start over` removes it. Questions about an individual sample still use the existing sample-guidance route.

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

`backend/assistant/tests/test_project_workflows.py` covers project/sample permissions, linked samples, viewers, revocation, forged context, pagination across scan batches, scan caps, exact versus partial counts, failed-QC/overdue/unassigned filters, refresh, current QC/field evidence, excluded historical records, Spanish input, ambiguity, provider bypass, no mutation and bounded query counts as sample counts grow.

```bash
cd backend
CELERY_BROKER_URL=memory:// CELERY_RESULT_BACKEND=cache+memory:// python -m pytest assistant/tests --nomigrations -q
```

No database migration is needed.
