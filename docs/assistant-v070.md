# OpenLIMS v0.70: daily work and project QC investigations

Both the full assistant and floating chat now offer actionable daily priorities and project-wide QC evidence reports. They extend the existing work, investigation, confirmation, artifact and workflow services. Rules mode and the OpenAI/Ollama bridges use the same services; no new model, migration, dependency or scheduled automation is added.

## Daily work

Ask **`What should I work on today?`**, **`Show my work`** or **`Show my work in project ALPHA`**. The default scope is work assigned to the authenticated user, including future and undated unfinished work. Completed work appears only when a pipeline QC gate is awaiting review. Cancelled work and final samples are excluded. Empty matches are not presented as a team-wide all-clear.

The panel explains recorded failures/rejected QC, waiting human workflow review, available overdue work, work due today, undated/upcoming work and blocked dependencies. Blocked work retains its blocker even when overdue; a deadline does not make it available. Missing results, step-form fields and invalid intake are disclosed. Non-finite numeric evidence is labeled and cannot be used for completion.

Choose **Assigned to me**, **Unassigned accessible work**, or **Accessible team work**, then an exact optional project code and a focus filter. Short follow-ups include **Only actionable**, **Only overdue**, **Only due today**, **Only QC**, **Only blocked**, **Show daily team work**, **Show daily unassigned work**, **Refresh my work** and **Next work page**. A selected sample/workflow still owns an ambiguous “What should I do next?”; an explicit daily-work request starts the daily view.

Available controls prepare one exact work item at a time:

- **Assign work:** one exact active username with current sample modification rights.
- **Preview start:** mark eligible pending work IN_PROGRESS through normal pipeline synchronization.
- **Update deadline:** choose a browser-local date/time or explicitly remove the deadline. The browser sends an offset/UTC timestamp; the confirmation preview shows the exact value. The API rejects naive timestamps.
- **Preview completion:** mark actually finished work COMPLETED only after current dependency, state, result and step-form checks. Completion does not approve QC.
- **Review workflow QC:** completed work at an awaiting-QC gate can receive an explicit human Approve/Reject/Rerun decision and reason from an authorized reviewer. Native separation of duties is enforced. Individual result QC reviews remain separate.

Typed supported commands also work without leaving chat, for example `Assign work item #21 for sample S-100 to maria` or `Add result concentration = 0 to work item #21 for sample S-100 unit ng/uL`. They retain the daily scope and freeze its work/evidence guard. Measurements are supplied by the user; existing result values are not overwritten by this flow. Unsupported repairs/retries or result corrections remain available through the existing sample/work controls.

Each change requires its own server-created preview and explicit Confirm button. Before confirmation, no lab record changes. Work/sample/run identities, current states, deadline, forms, dependency states and result evidence are checked again under database locks. Changed records, lost access or an ineligible assignee require a fresh preview. Duplicate confirmation returns its existing receipt; competing completion proposals commit one change. Audit failures roll back work and pipeline updates. After confirmation/failure/recovery the panel refreshes before re-enabling editors. Lost confirmation responses trigger server-status lookup; a lost preview can be refreshed and requested again without executing it.

Priorities are a deterministic operational ordering, not a scientific-importance score or a completion forecast. The server assesses at most the **250 earliest-due candidates**, filters/ranks that assessed set, and returns **25 rows per page**. A partial assessment is clearly marked and does not claim a complete global ranking. Narrow the exact project/focus when needed. Pages reread live records; concurrent updates can change positions. Up to 20 result examples are shown per work item, with its complete result count and source link. Validation/digests use the current complete target evidence. Today uses the application's displayed timezone and half-open calendar boundaries, not an inferred browser timezone.

## Project QC investigations and reports

Ask **`Investigate ALPHA’s QC failures and export a report`** or **`Investigate project ALPHA QC failures for last 30 days and export a report as CSV`**. The project code must resolve exactly; partial names, multiple projects and unsupported extra conditions are not silently broadened. **Investigate project QC failures** first asks for the exact project. The report includes accessible primary and linked samples; linked visibility does not grant write ownership.

The panel reports distinct quantities:

| Quantity | Definition |
| --- | --- |
| Recorded results | All matching result records in the selected creation-time window. |
| Assessed automated checks | Results whose `qc_passed` is true or false; unevaluated checks are excluded. |
| Failed checks / assessed rate | Failed automated checks divided by assessed checks, or unknown when none were assessed. |
| Rejected and pending/reopened result reviews | Current human result-review states, independent of the automated-check axis. |
| Distinct flagged results | The union of failed checks and rejected reviews, counting an overlapping result once. |
| Rejected/rerun work-item gates | Separate current QC gate decisions with a recorded review timestamp inside the window. Undated reviews are excluded. These are omitted when filtering by a result key, because the gate is not a key-level decision. |

Group result evidence by exact result key, directly linked instrument, result entrant or work type. Unknown instrument/operator provenance remains explicitly labeled; an instrument is never inferred from project co-occurrence. Source links expose actual records, values, automated-check reasons and human review notes. Operator groups describe traceability, not responsibility. Recorded differences and associations do not establish scientific root cause.

The UI supports rolling **1–365 day** windows and shared calendar periods, an exact optional result key, group changes and manual refresh. **Group by instrument**, **Group by operator**, **Graph failures by operator**, **Refresh this investigation**, **Export this investigation as PDF** and **Export this investigation as CSV** retain the current scope. Calendar filters show exact start/end/timezone; end boundaries are exclusive. Relative read filters are recalculated on refresh. Result evidence uses result creation time; work-item gate evidence uses its recorded review time. This is a current-record investigation, not a reconstruction of every historical review event.

An export first shows the exact project, filters, format and frozen absolute window. Confirmation rereads currently accessible evidence within that same window; counts may change after the preview. Generation is audited and returns a downloadable artifact with its SHA-256 checksum visible in chat. Reconfirming returns the same artifact. Downloads require current project and all contributing source-sample access, including for the creator. Losing a linked source sample, project access or a source record can invalidate an older download; generate a newly authorized report instead. Direct `/media/assistant_artifacts/` access is blocked in Django and production NGINX so it cannot bypass the authenticated download view; custom media servers/external storage must also keep that prefix private. Failed generation attempts clean up newly stored files before the database action rolls back.

The investigation refuses scopes over **5,000 combined result/work-gate records**, asking for a narrower window/key instead of reporting a partial failure rate. Chat shows up to 50 groups, 50 flagged results and 50 gate examples. **CSV includes all bounded group/failure/gate evidence** and escapes spreadsheet formula prefixes. **PDF shows up to 100 groups, 200 flagged results and 200 gate examples**, discloses those limits and truncates long reasons to 1,000-character excerpts; use CSV for complete text. Rates and totals use the complete bounded scope rather than displayed examples. The artifact receipt’s row_count counts flagged-result plus work-gate evidence records; summary result totals also include passing/unevaluated records.

## Saved views, permissions and API

Saved conversations retain query filters/stable references, not prior evidence or approval tokens. Reopening reloads current accessible work/results and does not replay changes or regenerate reports. Topic changes clear the active panel through normal conversation context handling. Read-only users can inspect accessible evidence, while mutation/QC controls follow current native permissions. Both `/api/` and `/api/v1/` aliases work; new integrations should use the versioned routes.

| Method and route | Request / behavior |
| --- | --- |
| `GET /api/v1/assistant/daily-work/` | `scope=mine|unassigned|team`, `focus=all|actionable|overdue|today|qc|blocked`, optional exact `project`, and `offset`. Returns the assessed priorities and fresh work digests. |
| `POST /api/v1/assistant/daily-work/actions/` | `operation`, `work_item_id`, displayed `digest`, optional daily `scope`, and exactly the operation-specific fields: `assignee` for DAILY_ASSIGN, `due_at` for DAILY_DUE, or `decision`/`reason` for WORKFLOW_REVIEW. DAILY_START/DAILY_COMPLETE need no additional fields. Returns a preview. |
| `GET /api/v1/assistant/project-investigations/{project_id}/` | One of `days` or `period`, optional exact `key`, and `group_by=key|instrument|operator|workflow`. Returns current QC evidence. |
| `POST /api/v1/assistant/project-investigations/{project_id}/export/` | The same investigation filters plus `output_format=PDF|CSV`. Returns the export preview. |
| `POST /api/v1/assistant/actions/{token}/confirm/` | Existing `{"confirm": true}` ownership, expiry and idempotence controls. |
| `GET /api/v1/assistant/artifacts/{id}/download/` | Existing artifact download, with extra current source-access checks for the new project reports. |

Unknown fields, duplicate query filters, conflicting windows and unsupported action fields are rejected. Query context and client-supplied digests never grant permissions. Report generation is synchronous within the existing confirmed action; configured pipeline automation retains its normal worker requirements.

## Upgrade and verification

Rebuild/restart the API and frontend. For production, **rebuild the `web` image** to install the private-media NGINX rules; restarting an older image alone does not install them. `VERSION`, generated footer and README current versions are **v0.70.0**. Both READMEs contain exactly the latest three release sections/table rows: **v0.70, v0.69 and v0.68**.

Tests cover actual HTTP/streamed daily work and project export/checksum/download flows; PostgreSQL competing completion proposals; snapshot staleness, role/access/assignee changes, required fields and QC separation; exact scopes, pagination/caps, false/zero/non-finite values and time boundaries; direct provenance and separate overlapping QC axes; frozen export windows, PDF/CSV bytes, formula protection, file cleanup and revoked downloads; fresh saved views and provider dispatch; and both chat surfaces with normal/stale-preview/interrupted-confirmation/access-revocation scenarios. Provider adapters are simulated; no live-model fluency benchmark or scientific validation is claimed.
