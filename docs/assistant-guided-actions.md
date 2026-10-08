# Confirmed lab actions (v0.40.0)

The assistant can turn a sample conversation into a **single, reviewable lab action**. These commands work with OpenLIMS Rules, OpenAI, and Ollama. Supported commands are parsed by the backend and bypass the external model; providers do not receive database credentials or execute SQL.

## Walkthrough

1. Ask `What next for sample DEMO-360-001?` using a sample you can modify.
2. Ask `Assign the next step to maria`. Use an exact, active username. If multiple steps are available, specify one: `Assign step 2 for sample DEMO-360-001 to maria`.
3. Read the preview: project, sample, pipeline run, step, work item, current assignee and proposed assignee. **No lab record changes before Confirm.** Cancel if the target is wrong.
4. Select **Confirm** within 15 minutes. OpenLIMS checks current permissions and records again, then records the assignment and its audit event.
5. Enter an actual measurement with `Add result concentration = 43 to step 1 for sample DEMO-360-001 unit ng/uL`. The value is an example, not a suggested measurement.
6. Review and confirm. The new result has `PENDING_REVIEW` QC status. Review, work completion and pipeline gates remain separate human decisions.

A result is only a proposed draft until confirmation; confirmation saves a normal **unreviewed** result. There is no new persisted draft-result status.

## Supported commands

| Intent | Example |
| --- | --- |
| Assign a numbered step | `Assign step 1 for sample SAMPLE-001 to maria` |
| Assign the uniquely available step | `Assign the next step to maria` (after selecting a sample) |
| Reassign exact work | `Reassign work item #59 to michael` |
| Add a number | `Add result concentration = 43 to step 1 for sample SAMPLE-001` |
| Add a string | `Add result interpretation = "PASS" to work item #59` |
| Add a boolean | `Add result detected = true to work item #59` |
| Spanish assignment | `Asigna paso 1 para muestra SAMPLE-001 a maria` |
| Spanish result entry | `Agrega resultado concentration = 43 a paso 1 para muestra SAMPLE-001` |

Use the workflow's exact result keys and types. Numbers must be finite, strings must be quoted, and booleans are `true` or `false`. An optional `unit ng/uL` suffix records a unit without conversion. Configured work accepts only configured keys. Existing results are never overwritten: open the sample's results interface to correct them. Responses and preview labels currently use English, including for Spanish commands.

Sample context can supply a missing sample ID; an explicit sample ID replaces it. An explicit work item that conflicts with retained sample context is refused: clear context or specify the correct sample. Step numbers select the current active/blocked run, never a historical run. “Next step” must resolve to exactly one ready/in-progress work item; it never picks among parallel branches. Clarification responses clear sample context; resend a complete command after correcting the problem.

## Controls

- Requesters and assignees must be active and have sample modification access. Linked-project visibility alone and viewer access do not permit these actions.
- Available work must be pending/in progress and still awaiting QC review. Blocked, failed, completed, cancelled and reviewed work are refused.
- Previews freeze the work item, sample, run and step. Confirmation uses server-owned payloads, locks the relevant records and rejects changed records, permissions, inactive assignees, changed schemas and duplicate result keys.
- Tokens belong to the requesting user, expire after 15 minutes and can be cancelled. Reconfirming a completed token returns the existing outcome without executing it again. Separate duplicate result proposals cannot overwrite the first result.
- Each change links its audit event to the assistant action and sample/project/work item. Assignment does not imply QC reviewer assignment; result entry does not approve QC or mark work complete.
- Stored notes are treated as data. These routes do not ask a model to interpret instructions in notes or rewrite previews.

This release covers assignment and new result entry. Preparing sequencing batches is still a separate operation; these commands do not assemble or start one automatically.

## Validation

`backend/assistant/tests/test_guided_actions.py` exercises actual chat, confirmation, cancellation, database records and audit events. It covers English/Spanish input, ambiguous parallel steps, typed values, duplicate results, stale work, changed schemas, revoked access, assignee eligibility, token ownership/expiry, forged context/payloads and provider bypass. Run alongside the existing assistant tests:

```bash
cd backend
CELERY_BROKER_URL=memory:// CELERY_RESULT_BACKEND=cache+memory:// python -m pytest assistant/tests --nomigrations -q
```

No schema migration is needed. Local SQLite tests exercise repeated requests, not simultaneous PostgreSQL transactions.
