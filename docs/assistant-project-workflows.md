# Questions across project samples (v0.41.0)

Ask about several samples together in the Assistant page or floating widget:

- `Which samples in project DEMO-360 are blocked, and why?`
- `Which samples in DEMO-360 are missing results?`
- `Which samples in project DEMO-360 need QC?`
- `Which samples in project DEMO-360 are ready?`
- `Show samples in project DEMO-360 workflow overview`
- `¿Qué muestras en proyecto DEMO-360 están bloqueadas y por qué?`
- `¿Qué muestras en proyecto DEMO-360 tienen campos faltantes?`
- `¿Qué muestras en proyecto DEMO-360 necesitan QC?`

Use an exact project **code**, not a name or approximate spelling. Multiple project references ask for a single choice. The table links each sample and shows its pipeline run, step, reason and recorded work assignee where available. Assignees are not inferred to be QC reviewers.

After selecting a project, `Which are ready?`, `Which are missing results?`, or `And QC?` switches the filter and refreshes the first page. `Next page` / `Siguiente página` continues the same filter. A full question naming a different project switches projects. The context bar shows the selected project and filter; Clear or `Start over` removes it. Questions about an individual sample still use the existing sample-guidance route.

## Meaning of the filters

| Filter | Meaning |
| --- | --- |
| Blocked | At least one recorded failure, unmet dependency, activation gate, missing/invalid required field, outstanding QC gate, or blocked run. This is an operational summary, not a change to sample status. |
| Missing results | Required results missing, empty or using the wrong type, plus required form fields identified by pipeline validation. |
| QC | Completed work awaiting required QC, including rejected/re-run review states. Pending work is not automatically treated as ready for QC. |
| Ready | A ready/in-progress step has its required fields, satisfied dependencies and active work awaiting review. Review and complete that work through the existing controls. This does **not** mean the sample is QC-approved or sequencing-ready. |
| Workflow overview | Current step evidence for all samples on the page, including samples with no active pipeline. |

A sample can have available work in one branch and a blocked step in another. Ordinary downstream dependencies count as blockers but do not prove the whole sample is stalled. Completed, skipped and cancelled steps and historical runs do not supply current blockers. Samples marked REPORTED, CANCELLED or ARCHIVED are excluded.

## Access, paging and freshness

Only project members or admins can query the project. Samples belong through either their primary project or a linked project and still pass the sample access filter. Viewer members can read; linked membership does not grant editing. Every question and next-page request rechecks membership. Access denial clears the retained project context.

Each page checks at most **25 samples** in database-ID order. It reports the number checked, accessible non-final sample count and matches on that page. If the first page has no matches but more samples remain, use Next page; zero on a page does not mean zero in the project. At most six matching reasons per sample are shown, with an explicit additional-reasons count and a link to inspect all steps. Refresh the original question for a new first page. These are live pages rather than a frozen report; concurrent changes can affect later pages.

These queries are read-only, use batched ORM retrieval, and work without a provider. They bypass external-model interpretation and rewriting; OpenAI/Ollama do not directly query the database. A project summary does not select samples for bulk writes or create a confirmation action. There is no unrestricted SQL or semantic search in this feature.

## Verification

`backend/assistant/tests/test_project_workflows.py` covers project/sample permissions, linked samples, viewers, revocation, forged context, pagination, empty match pages, current QC/field evidence, excluded historical records, Spanish input, ambiguity, provider bypass, no mutation and bounded query counts as sample counts grow.

```bash
cd backend
CELERY_BROKER_URL=memory:// CELERY_RESULT_BACKEND=cache+memory:// python -m pytest assistant/tests --nomigrations -q
```

No database migration is needed.
