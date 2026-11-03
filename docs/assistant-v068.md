# OpenLIMS v0.68: instrument imports without leaving chat

Open the full assistant or floating widget and choose **Import instrument data**. You can also say `Import this sequencer file into project ALPHA`. The chat provides the file chooser, instrument mapping, validation preview, confirmation, job receipt, recovery controls and downloadable row report. This flow supports mapped UTF-8 CSV/TSV/TXT instrument exports using existing instrument profiles.

## Upload and choose the mapping

1. Select the instrument profile. Its sample-ID column, delimiter, source columns, result keys, types and configured limits appear in chat. Each profile owns one configured set of column mappings; the assistant uses that set. Mapping configuration requires an administrator.
2. Choose an accessible project and enter the instrument's run ID. A project explicitly named in the chat request is preselected. Write targets are not inferred from the open page.
3. Attach one file, up to **10 MB and 10,000 data rows**. Header detection and configured metadata/header offsets use the existing instrument CSV parser.
4. Choose **Skip exact repeated rows within this file**, or clear it for intentional replicate measurements. This choice is part of the prepared import.
5. Press **Validate file and preview import**. Uploading stores a prepared import and file; it does not import measurements or enqueue processing.

The same instrument plus exact run ID identifies one import. Retrying an interrupted upload with the same file, project and repeat policy returns its existing preview or receipt. A conflicting file or project cannot silently replace a reserved run. Use a new run ID for a distinct instrument run. Identical data under a different run ID is treated as a new run, not globally deduplicated.

Uploaded contents are processed by Python and do not enter OpenAI/Ollama prompts. The chat command and provider bridge can open the upload controls; the user selects the file and mapping. File storage names are randomized; original filenames are retained for the receipt.

## Validate every data row

The preview accounts for all parsed data rows before any measurement is written. It shows the first 20 rows, and the expandable report shows up to 50. **Download row report** provides the complete file-row accounting, including rejected and repeated rows.

Validation checks header uniqueness, every configured source column, row width, sample identifiers, result types, finite numbers and configured limits/allowed values. A row with any invalid mapped value is rejected as a whole. Missing mapped cells are allowed when another mapped measurement exists; rows with no mapped values are rejected. Unmapped file columns are explicitly listed as ignored.

Existing samples must be writable in the selected primary project, or be unassigned samples the uploader can modify and associate with that project. Inaccessible or differently owned-project samples are rejected without exposing their stored values. Case variants resolve to the same existing sample identity. New IDs create GENERAL samples using the native import behavior when their published intake form permits it; otherwise register the samples with their required intake values first.

Exact repetition compares all parsed file-column text, including unmapped columns. It does not infer scientific equivalence from matching sample IDs or numerically equivalent values such as `5` and `5.0`. Distinct rows for the same sample remain separate measurements. Clearing the repeat checkbox retains exact repeated rows as replicates.

Before processing, the row equation is:

```text
rows received = validated rows to import + rows rejected + exact repeats skipped
```

After successful processing:

```text
rows received = rows imported + rows rejected + exact repeats skipped
```

Each imported row creates one work item linked to the import job, and its mapped results. Multiple measurements for a sample are retained in separate work items; the import does not overwrite older result sets. Samples, work items, results and audit entries use the existing database tables.

## Confirm and follow the receipt

Review the instrument mapping, selected project/run, row counts and rejected/repeated-row report. Press **Confirm action** in the full assistant or **Confirm** in the widget. Confirmation rechecks the file hash, frozen mapping/parse configuration, row-target identities, uploader permissions and validation plan before enqueueing the job.

The Celery worker performs the checks again and imports the validated set in one PostgreSQL transaction. A processing failure rolls back that set, including newly created samples, work items, results and associated audit entries. Rejected rows and explicitly skipped repeats remain in the report; they are not part of the committed measurement set. A failed job reports zero imported measurements and marks its previously validated rows as not imported.

Repeated confirmation returns the same action, and duplicate worker deliveries serialize on the import-job lock. The dedicated task uses late acknowledgement and worker-loss redelivery. Processing errors produce failed receipts for explicit recovery; transient database/I/O errors escaping an attempt or its finalization use bounded task retries. Uncommitted changes roll back if the worker dies; a completed job returns its receipt on redelivery. Completion-action finalization can also be retried after the data commit, and is restricted to the action generation that ran. This relies on the database, file storage, broker and worker being available; the receipt and explicit recovery controls expose failures rather than claiming missing acknowledgements mean success.

Both chat interfaces display received/imported/rejected/repeated counts and results created, then refresh the queued action to its completed/failed status. Automatic status checks run for about three minutes; **Refresh import status** remains available afterward. The row-report CSV escapes spreadsheet formula prefixes. Its row numbers refer to parsed data rows after header/metadata handling, not physical file line numbers.

## Recover in chat

| Situation | Action |
| --- | --- |
| Upload response interrupted | Retry the same file and run ID to recover the existing preview; do not invent a new run ID for the retry. |
| Reopen the chat or find an earlier upload | Say `Show my instrument imports`, then `Show instrument import #123`. The list shows the latest eight accessible uploads owned by the current user. |
| Check the current import | Say `Check import status` or `How did the import go?`, or use the receipt's Refresh button. |
| Mapping, samples, permissions or file changed | Use **Revalidate and preview**, review the fresh counts/mapping, and confirm again. |
| Confirmed but worker delivery is uncertain | Use **Resume queued import**. It resends the same authorized generation, without creating another measurement set. |
| Failed processing | Restore access/correct configuration as needed, revalidate the stored file and confirm a fresh preview. The failed set committed no measurements. |
| Completion receipt still needs synchronization | Use **Finalize import receipt** if offered. Completed measurements are not imported again. |
| Successful import has rejected rows | Correct and upload just those rows under a separate run ID. Re-uploading the entire file under a new run ID intentionally adds another run. |

Revalidation replaces previous proposals and can supersede a confirmed queue entry before processing starts. Processing holds the job lock; recovery controls return a “being processed” response when the worker already owns it. Old delivery generations cannot process a replacement preview. The original uploader must perform revalidation/resume; administrator visibility alone does not transfer ownership of the file task. Current project access is checked on status and report downloads.

## API

Both `/api/` and `/api/v1/` routes are supported; new integrations should use the versioned routes.

| Method and route | Request / behavior |
| --- | --- |
| `POST /api/v1/assistant/instrument-imports/` | Multipart fields: `instrument` ID, `project` ID, `run_id`, one `uploaded_file`, and `skip_duplicates` boolean. Returns the validated assistant preview and prepared job. |
| `POST /api/v1/assistant/actions/{token}/confirm/` | JSON `{"confirm": true}`. Uses existing action ownership, expiry and confirmation rules. |
| `GET /api/v1/assistant/instrument-imports/{id}/` | Current status, frozen mapping, bounded row-report excerpt, full counts and current action. |
| `GET /api/v1/assistant/instrument-imports/{id}/report/` | Authorized download of the complete row receipt as CSV. |
| `POST /api/v1/assistant/instrument-imports/{id}/revalidate/` | Empty JSON object. Validate the stored file/current configuration and return a fresh proposal. |
| `POST /api/v1/assistant/instrument-imports/{id}/resume/` | Empty JSON object. Recover delivery/finalization of an already confirmed generation. |

The native import retry endpoint cannot bypass chat revalidation. Chat-created jobs also reject edits and deletion through the native import API, preserving their reserved run identity and receipt. Neither a client-supplied context nor an LLM-provided command can approve or execute an upload without its server-created confirmation token.

## Upgrade and validation

Rebuild the API and frontend, and **restart the Celery worker** so it registers the new import task. This reuses existing PostgreSQL, Redis, file storage and Celery; no migration, dependency, model download or scheduled coding automation is added. `VERSION` and the generated footer are **v0.68.0**. Both READMEs contain exactly three release-update sections and table rows: **v0.68.0, v0.67.0 and v0.66.0**.

This release also fixes v0.67 registration incorrectly requiring an undefined `samples` feature flag when optional-module feature enforcement is enabled. Core registration/import availability follows permissions; existing optional module flags are preserved. Numeric previews and processing now share the finite-number validator, closing acceptance of NaN/infinity.

Tests cover multi-part HTTP staging, confirmation and receipts; complete 100-row accounting; exact-repeat policy and retained replicates; case variants and false/zero values; bad/missing headers, invalid numbers/text and duplicate upload fields; cross-project/owner access; file/mapping/permission changes; broker publication failure and resume; atomic rollback; stale delivery generations; action-finalization recovery; and two concurrent PostgreSQL workers producing one measurement set. Browser tests exercise upload, invalid-file correction, interrupted-response recovery and CSV receipt download in both chat surfaces. Provider adapter tests use simulated responses; no live-model fluency or scientific-validation claim is made.
