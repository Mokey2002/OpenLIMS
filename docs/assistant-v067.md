# OpenLIMS v0.67: register and assign samples in chat

The assistant can complete a combined registration and sample-assignment task from either chat view. It collects missing details, validates the configured fields, previews the exact records, and waits for explicit confirmation. No tab navigation or language model is required.

## Start a task

Use the **Register samples and assign them** suggestion, or type:

```text
Register samples and assign them
Register 10 DNA samples in project ALPHA and assign them to maria
Register 1 PLASMA sample in project ALPHA and assign it to me
Register 2 DNA samples in project ALPHA and assign them to maria with source=blood
```

Use an accessible exact project code, or quote an exact project name containing spaces. The assignee must be an active Tech/Admin who can modify samples in that primary project. Usernames are matched exactly, ignoring case; first names and email addresses are not used to select people. `me` selects the authenticated user.

An incomplete registration such as `Register samples` also starts a guided registration task, with no assignment unless requested. Existing complete single-registration commands retain their established behavior. The new combined form is available through the shared OpenAI/Ollama tool catalog as `sample_registration`, and through the existing `samples` bridge. All routes use the same current-user permissions and server-created proposals.

## Answer one question at a time

For the generic combined task, an example conversation is:

| Assistant asks | You reply |
| --- | --- |
| How many samples? | `10` |
| Which project? | `ALPHA` |
| What sample type? | `DNA` |
| Who should receive the samples? | `maria` |
| What is Source for all 10 samples? | `blood` |
| Additional required intake fields, if configured | The requested value |

Only the missing questions are asked. The selected project remains bound by ID through renames and code reuse. Each turn rechecks current write permission and assignee eligibility. `Thanks` preserves the draft. `cancel`, `never mind` and `start over` discard it; a new explicit task or read starts a new topic.

Configured legacy sample custom fields and the selected type's published intake form are validated. Conditional fields, dropdowns, date/number/boolean types, required fields and numeric bounds use the existing validators. Values such as `false` and `0` are preserved. Archived intake types require a different type. All supplied values are shared by **every new sample** in this task.

Reply with a value, or supply several fields together using `with source=blood, quantity=0`. Use JSON quotes for text containing commas or command-like words. When a key exists in both field systems, name the system explicitly: `with custom_fields={"source":"blood"}, form_values={"source":"instrument"}`. Unknown keys and malformed/duplicate field entries require correction before a proposal is generated. A general field-map error can be replaced with a complete corrected `with ...` reply.

## Preview and confirm

The preview lists every generated sample ID, project, type, initial RECEIVED status, sample assignee, and shared custom/intake values. Review it and press **Confirm action** in the full assistant, or **Confirm** in the widget. A chat reply such as `yes` does not execute it. Use **Cancel** on the proposal to cancel it after preview.

The task creates samples, their field values, initial assignee and creation audit events in one transaction. Before writing, it rechecks the actor's access, the assignee's identity/role/access, the frozen intake form, field values, sample count and generated IDs. A duplicate/conflicting ID, changed form or permission failure rolls back the whole task. Creation audit entries include the assignee and supplied values. Reconfirming the same completed action returns the existing result without duplicate records.

Assignment updates each sample's assignee. Pipeline steps and work items have separate assignments, available through existing commands such as `Assign step 1 for sample S-100 to maria`. Other existing chat actions include result entry, supported sample-status changes, inventory operations and QC review, with their own permissions and previews. This release does not execute arbitrary action chains.

Both chat views show a completion receipt with success/failure counts. If the confirmation response fails or is interrupted, the browser reads the action's current server status without resending the write. A completed action restores its returned sample context; a failed action shows its error and removes the stale confirmation button. If that status lookup also fails, the existing proposal remains visible and the user can retry; confirmation is idempotent for the same token. The result context supports existing follow-up commands using the created sample selection.

## State, deployment and validation

Draft state is signed, user-bound and limited to 24,000 token characters, with a rolling 30-minute expiry. It contains user-supplied task details, not an authorization grant; permission checks still run on every turn and confirmation. It is signed rather than encrypted. Drafts are not durable saved-chat tasks. Reloading or reopening an older conversation requires starting the registration again; confirmation tokens are never replayed by saved chats. The existing proposal expiry and ownership rules apply.

No migration, dependency, model download or scheduled automation is added. Rebuild the frontend and restart/reload the API. `VERSION` and the generated footer report **v0.67.0**. Both READMEs retain exactly the three latest release-update sections and rows: **v0.67.0, v0.66.0 and v0.65.0**.

Regression coverage includes multi-turn question collection, one-command preview/confirmation, duplicate confirmation, rollback after a late ID conflict, required/conditional intake fields, false/zero values, project rename/code reuse, actor and assignee permission changes, expired/tampered/cross-user drafts, cancellation, unsupported mutations, both provider bridges, and real authenticated HTTP/ASGI streaming followed by confirmation. Browser checks cover the task preview and successful/failed/interrupted confirmation in both chat interfaces. Provider tests use simulated responses; no live-model accuracy claim is made.
