# OpenLIMS v0.69: guided sequencing preparation

Ask **`Help me prepare sample S-100 for sequencing`** from the full assistant or floating chat. Choose **Help me prepare a sample for sequencing** to be asked for an exact sample ID first. This opens a live checklist based on the sample's configured pipeline. The same deterministic services work in Rules mode and through the OpenAI/Ollama provider bridge.

## Walk through the configured workflow

1. **Select the sample.** Read access is checked against current primary/linked-project membership or permitted ownership. The guide never selects a write target from the open page or an approximate sample name.
2. **Select a configured pipeline if needed.** When no active/blocked run exists, choose an existing active template, preview its start, and confirm. The native pipeline service creates its steps and activates eligible work, including any configured automation. Templates are not invented or edited by the guide. A previous completed run is labeled as history; starting another run is an explicit separate decision.
3. **Review the checklist.** It shows step status, work assignee, unmet dependencies, missing result/form fields, recorded results and their QC, and the work-item QC gate. Sample intake errors are shown and must be corrected in the sample record. Failed steps, closed activation gates and unfinished dependencies are explained; the assistant cannot bypass them. Use the existing sample retry/configuration controls for unsupported repairs, then refresh the guide.
4. **Assign available work.** Choose Assign work and enter an exact eligible username. The existing confirmed assignment flow is used.
5. **Record actual observations.** Record result offers configured keys when requirements define them; otherwise enter a key and explicit type. Values are numbers, strings or booleans, and existing result keys are not overwritten. Use the existing typed result command with an optional `unit ng/uL` suffix when recording a unit. New results remain unreviewed. Record step form uses the frozen form's types, choices, bounds and conditional fields, and requires an audit reason of at least ten characters. Every submitted form value is validated before a preview is offered.
6. **Complete finished work.** Preview work completion appears only for available unfinished work with its configured required results/form fields present and valid under the native pipeline validator. Confirmation marks the work complete and invokes normal pipeline synchronization. It does not approve QC.
7. **Record a human QC decision.** At an awaiting-QC step, an authorized reviewer can select Approve, Reject or Rerun required, supply a reason, review the preview and confirm. There is no default decision. Current role, access, dependencies, required evidence and configured separation of duties are checked again. Failed automated QC is disclosed in the preview; the human reviewer makes the decision. Result-level QC and the workflow work-item gate are separate: approving the gate does not approve individual results.

Each mutation requires its **own preview and explicit Confirm button**. Asking for a guide, entering values in an editor, selecting a template, refreshing or saying “yes” does not execute a change. Confirmation tokens belong to the requester, expire after fifteen minutes, and can be cancelled with the proposal's Cancel button. Reconfirming a completed token returns its receipt without executing again.

The checklist refreshes after confirmed, failed or recovered action status changes. Editing remains disabled until the current refresh finishes so a delayed response cannot erase an editor opened against old evidence. Refresh manually after another team member changes the workflow. A stale plan or changed evidence returns a request for a fresh preview; it does not execute against a wider or newer target set.

## Understand sequencing availability

The guide identifies sequencing only by the configured **exact `SEQUENCING` analysis/work-type code**, rather than guessing from procedure names. It reports the sequencing step as available only when that step is READY, its dependency steps are completed/skipped and its run is ACTIVE. Output results or step-form requirements may still be pending and remain visible in the checklist.

This reports availability in the configured application workflow. It does not certify scientific suitability, assess unspecified laboratory criteria, start a physical sequencer, or mean every result is QC-approved. No matching sequencing step or multiple matching steps produce an unknown assessment and an explanation, not an inferred target. In-progress/finished steps, final samples and run failures have distinct messages. Completed historical runs are not silently reused or restarted.

## Continue and recover

- **What should I do next?**, **Why is preparation blocked?**, **Check requirements**, **Check QC** and **Refresh preparation** reread current records for the selected sample.
- Use the checklist controls or existing full commands such as `Assign work item #21 for sample S-100 to maria` and `Add result concentration = 5 to work item #21 for sample S-100`. Same-sample supported actions retain the guide; an explicitly different target does not inherit it.
- If a confirmation response is interrupted, both chat interfaces retrieve the action's server status before showing success/failure, then refresh the checklist. If a preview response is interrupted, refresh and request a new preview. Old proposals still require their own confirmation and become stale after relevant workflow changes.
- A conversation guide remembers the sample through a signed, user-bound reference valid for thirty minutes. Expired, forged, cross-user or inaccessible context cannot restore it; start again with the exact sample ID. Courtesy replies preserve the current clarification. Changing topics clears the active guide through normal conversation context handling.
- Saved conversations store only a stable sample reference for a guide. Reopening rereads current accessible evidence and issues fresh read context; no results, workflow snapshots or approval tokens are replayed. Revoked access removes the protected checklist.
- **Cancel preparation** closes the guide. Use each outstanding proposal's Cancel button to cancel it; closing a guide does not confirm or cancel unrelated proposals.

Viewer and linked-project Tech access can show a read-only checklist; it does not grant sample write ownership. QC controls separately follow the native reviewer/access policy. Inactive users and final samples cannot mutate through this guide. Status retrieval/downloaded conversation reads recheck access rather than trusting client context or a plan digest.

## Limits and API

The guide handles the sample's single active/blocked pipeline. It shows at most **50 steps**, the first **100 result records per displayed step**, and up to **50 active template choices**. A truncated step list has an unknown readiness assessment and disables guided mutations. Result-list truncation is disclosed; validation and the frozen evidence digest still use the current complete result set. Open the work/sample view to inspect additional evidence or templates. No new database table, migration, dependency or external model is added.

Both API prefixes work; new integrations should use `/api/v1/`.

| Method and route | Behavior |
| --- | --- |
| `GET /api/v1/assistant/workflows/{sample_id}/` | Current authorized checklist, availability explanation, evidence, eligible controls and `plan_digest`. |
| `POST /api/v1/assistant/workflows/{sample_id}/actions/` | Validate one structured action against the displayed digest and return a server-owned confirmation proposal. No laboratory records change. |
| `POST /api/v1/assistant/actions/{token}/confirm/` | Existing explicit `{"confirm": true}` ownership/expiry/idempotence checks, followed by locked revalidation and execution. |
| `POST /api/v1/assistant/actions/{token}/cancel/` | Existing cancellation for the selected proposal. |

Action requests accept exactly these fields; unrelated fields are rejected:

| Operation | Fields besides `operation` and `plan_digest` |
| --- | --- |
| `WORKFLOW_START` | `template_id` |
| `WORKFLOW_FORM` | `step_id`, `values` object, `reason` |
| `WORKFLOW_COMPLETE` | `step_id` |
| `WORKFLOW_REVIEW` | `step_id`, `decision` (`APPROVED`, `REJECTED`, `RERUN_REQUIRED`), `reason` |

The server freezes sample/run/step/work identities, statuses, dependencies, form schemas/values and result evidence. At confirmation it locks the sample, run, steps, work and existing results, rechecks the digest and permissions, and executes one action in a transaction. Template starts additionally freeze/recheck the chosen template configuration. Native pipeline synchronization and audit events are retained; each change also records its assistant-action ID. A processing error rolls back the action. Concurrent confirmation of one token starts one run, as enforced by PostgreSQL locks and the existing one-active-run constraint.

## Upgrade and verification

Rebuild/restart the API and frontend normally. This release adds no Celery task or new infrastructure; normal configured pipeline automation retains its existing worker requirements. `VERSION`, the generated frontend version/footer, and both README badges/current-version references are **v0.69.0**. Both READMEs contain exactly the latest three release sections/table rows: **v0.69, v0.68 and v0.67**.

Automated checks cover the full chat/confirmation/QC progression and real streaming HTTP; typed zero/false inputs; validated/audited step forms; stale result/template evidence; dependency and missing-field gates; exact sample selection and provider dispatch; owner/cancellation/expiry/forged-context protections; read-only and revoked access; separation of duties and reviewer-role revocation; rejected/rerun QC; saved-guide freshness; final samples/intake errors/step limits; concurrent PostgreSQL confirmations; and both chat surfaces with stale-preview, interrupted-confirmation and revoked-access recovery. Provider tests use simulated adapters; they do not establish a live-model fluency score or scientific validation.
