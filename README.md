# 🧪 OpenLIMS

<p align="center">
  <strong>Open-source, self-hosted Laboratory Information Management System for practical lab workflows.</strong>
</p>

<p align="center">
  <a href="#installation">Install OpenLIMS</a>
  ·
  <a href="#-features">Features</a>
  ·
  <a href="#-architecture">Architecture</a>
  ·
  <a href="#-local-development">Local Development</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-v0.54.0-blue">
  <img alt="License" src="https://img.shields.io/badge/license-Apache%202.0-green">
  <img alt="Backend" src="https://img.shields.io/badge/backend-Django%20REST%20Framework-darkgreen">
  <img alt="Frontend" src="https://img.shields.io/badge/frontend-React%20%2B%20Vite-61DAFB">
  <img alt="Database" src="https://img.shields.io/badge/database-PostgreSQL-336791">
  <img alt="Assistant" src="https://img.shields.io/badge/assistant-OpenLIMS%20%7C%20OpenAI%20%7C%20Ollama-purple">
</p>

**Getting started:** [Installation guide](#installation) · [Guía de instalación en español](README_ES.md#instalación-paso-a-paso)

---

## Overview

### v0.54.0 — Personal work priorities and conversational follow-ups

Ask **“What do I need to work on?”**, **“What's on my plate?”**, or **“Show my tasks”** without enabling an AI provider. The assistant shows up to 100 accessible unfinished work items assigned to the signed-in user, earliest deadlines first, with overdue/failure/QC-review flags and sample links. Unassigned and other people's work are excluded; completed/cancelled work is excluded. Future/undated work is included. This is a work list, not a complete dependency or QC task assessment. An empty list does not mean the whole lab has no pending work.

For the nine direct read/draft features connected in v0.53.0, missing inputs now trigger one plain-language question at a time. For example, the handover helper asks whose work to cover, accepts `me`, then asks who is taking over. Exact short IDs/usernames work without another model call; quote multi-word titles. With OpenAI/Ollama enabled, follow-ups such as `same for BETA` receive the verified previous feature arguments. New topics start fresh, and `never mind` or `start over` clears this feature context.

Conversation state is signed, tied to the requesting user and expires after 30 minutes. Every resumed feature rechecks current permissions. It stores request arguments, not result snapshots, and never authorizes changes. Write-command adapters do not receive this replay context; previews/confirmations remain unchanged. Both chat views use friendlier interpretation labels instead of raw JSON. Model follow-up tests use simulated responses, not a live-model quality benchmark. No migration is required.

### v0.53.0 — Shared OpenAI/Ollama feature dispatch

When rule matching cannot resolve a request, either configured provider can now return a validated feature request. OpenLIMS dispatches it with the authenticated user and existing conversation context. Enable the assistant LLM and LLM routing settings, then configure OpenAI credentials/model or the Ollama URL/model. Rules-only mode remains available.

The shared catalog covers 32 entries: direct connections for sample history, related experiments, reagent planning, project updates, quarantine-impact previews, data-quality reviews, workflow drafts, shift handovers and run comparisons; command adapters for analytics, attention, barcodes, calculations, charts, comparisons, confirmed jobs, inventory, investigations, notifications, QC, reports, samples/registration, sequences, SOPs, work items, guided assignments/results, sample guidance, project workflow queries, monitoring, identity, record search and migration search.

For example, a provider can interpret “Help Maria take over Peter's unfinished work” as a handover with source `peter` and recipient `maria`. Existing features recheck permissions, feature flags and record ambiguity. Missing required inputs ask for a complete request with those details; free-form clarification follow-ups are not automatically stored. Model-generated commands must still match the selected legacy parser. Unsupported conditions should produce clarification, not invented functionality; recognition quality depends on the configured model.

Both chat surfaces show an expandable provider interpretation, including the selected feature and arguments. Results remain deterministic and can retain the OpenLIMS Rules label: the provider interprets, while OpenLIMS executes. Writes only produce the existing server-generated confirmation previews; workflow drafts require explicit saving in the designer. The model cannot confirm an action, execute SQL/code, or supply permissions. Global legacy migration search through this bridge is admin-only.

Validation uses mocked provider responses to exercise both adapters and backend execution; it is not a live-model accuracy benchmark. A catalog coverage regression detects newly added assistant routers without an explicit dispatch connection. No database migration is required.

### v0.52.1 — Deterministic investigation privacy regression

Fixes an intermittent CI test failure: the digits of a private result (`9999`) could appear in an unrelated timestamp. The investigation test now reproduces that timestamp and checks actual result IDs/values, peer records and aggregate counts instead of scanning the entire response for digits. Application behavior and permissions are unchanged; no migration is required.

### v0.52.0 — Workflow drafts, handovers and run comparisons

The remaining collaboration helpers work in both assistant chat views:

- **Workflow drafts:** an administrator can ask `Create a workflow with EXTRACT@1, QC@1, SEQUENCE@2, REVIEW@1`. Replace these examples with existing active procedure codes/versions (or exact names). Missing or ambiguous procedures stop the draft. Click **Review workflow in designer**, enter a code/name, review dependencies, QC gates, conditions and automation, then save explicitly. Drafts start inactive, use sequential dependencies and never infer QC gates or automation. The designer rechecks procedure versions; text edits in chat change only the copyable note. Up to 30 steps are supported.
- **Shift handovers:** `Prepare peter's handover for maria` uses exact active usernames. The editable draft lists up to 100 unfinished assigned work items visible to the requester and both participants, with deadlines, overdue flags and failed/rejected/rerun QC review flags. Completed/cancelled work is excluded. Dependencies and unrecorded blockers need manual review. Nothing is sent or reassigned; recheck permissions before sharing a copied draft.
- **Run comparisons:** `Compare runs <experiment-public-ID> and <experiment-public-ID>` also accepts unique exact titles. Both experiments must be accessible and the notebook feature enabled. Tables compare current workflow definitions, recorded parameters/status, linked lot identities and current structured result blocks (including QC if recorded there). Steps/blocks align by position, so review changed ordering. Missing data is unknown; links do not prove consumption and differences do not establish causes. Free text, historical revisions and external QC are excluded. Limits: 50 steps, 100 lots, 50 result blocks per run, 4,000 displayed characters per value; partial comparisons are marked.

No database migration is required. Existing installation instructions below still apply.

### v0.51.0 — AI impact previews and data-quality reviews

Two new read-only reports work in both assistant chat views, with evidence tables, record links and prompts based on existing records:

- **Lot quarantine impact:** ask `What would be affected if we quarantine lot LOT-12?` or `Preview quarantine impact for lot LOT-12`. Reviews accessible active reservations, recorded consumption and current notebook links. Distinguishes planned dependencies from past use, shows work/experiment status, and links the affected records. It does not quarantine anything or infer that past results failed. Notebook evidence requires the notebook feature and access to each linked target. Shows at most 25 rows per evidence category, with a partial-preview notice; rows are evidence, not unique specimen counts.
- **Project data-quality review:** ask `Check project ALPHA for suspicious records` or `Review data quality for project ALPHA`. Flags sample IDs differing only by case/punctuation as possible duplicates, missing required custom metadata, invalid saved intake forms (including conditional fields), differing/missing result units within the same analysis/work type and result key, and unusual timestamps/deadlines. Each finding is a review prompt, not a scientific conclusion or automatic correction. Known compatible units and valid zero/false metadata are accepted.

Quality reviews scan up to 250 primary-project samples, 1,000 related work items and 1,000 results, in ID order, displaying at most 100 findings. Partial scans and display limits are explicit; a clean scanned subset is not certification of the entire project. Rerunning checks current records and permissions. No database migration is required for this release.

### v0.50.2 — Stable registration follow-ups and database-safe values

Registration follow-ups retain the project ID, so renamed/reused codes cannot redirect a pending request and punctuation in project codes no longer breaks replies. Every follow-up rechecks role and project access. After upgrading, restart any unfinished registration from v0.50.1 or earlier; its code-only context is no longer safe to resume.

Duplicate keys inside JSON objects, null characters, invalid Unicode and non-finite values are rejected before a proposal and checked again at confirmation. Oversized numeric fields return a validation message rather than an error. Normal Unicode text and quoted punctuation remain supported. No database migration is required.

### v0.50.1 — Stricter registration and stock estimates

Sample registration rejects negated/embedded requests, duplicate fields, malformed field lists and trailing instructions. Use JSON quotes for values containing commas or significant punctuation: `Register 2 plasma samples in project ALPHA with source="blood, frozen."`. Correct invalid fields with another `with ...` reply; project permissions are checked again. Confirmation validates frozen sample IDs and sample type before creating records. Overlong generated IDs are rejected at preview time.

Reagent planning revalidates configured quantities/units even if imported without form validation. Invalid stock, incompatible reservation units or reservations exceeding stock produce an **unknown** estimate, never a claim that stock is sufficient. Released reservations remain excluded. No database migration is needed for this patch.

### v0.50.0 — Five practical AI lab helpers

- **Sample history:** `What happened to sample S-100?` summarizes the latest 50 audit/custody events, actors and current work/QC state, with a link to the sample. Missing events are not reconstructed.
- **Related experiments:** `Find similar experiments about plasma extraction` searches titles, current notebook content and accessible template names. Every keyword must match; results are limited to 20 accessible experiments. This is keyword search, not a claim of scientific equivalence. The notebook feature must be enabled.
- **Reagent planning:** `Plan reagents for 30 samples using procedure EXTRACT version 1` calculates configured quantities against active, unexpired stock after reservations, converting compatible units. Missing configuration or ambiguous versions ask for clarification. It does not reserve stock or include unconfigured controls, repeats or waste.
- **Sample registration:** `Register 12 plasma samples in project ALPHA` asks for required custom fields, then shows a preview. Reply `with source=blood` (using your configured field names and all required values). Only explicit confirmation creates samples. Role, project access and required fields are checked again; the existing bulk limit applies.
- **Project updates:** `Write a short progress update for project ALPHA` creates an editable draft in either chat view, with a source project link and a copy button. Counts describe current primary-project records. Nothing is sent; edits remain in the current chat view.

**Upgrade/configuration:** run `docker compose -f deploy/docker-compose.yml run --rm api python manage.py migrate` after rebuilding the API. In Django admin (`/admin/`), open **Pipelines → Procedure definitions**, select the correct procedure/version, and add **Procedure reagent requirements** with inventory item, positive quantity per sample and compatible unit. Save before requesting a reagent plan. No reagent quantities are guessed or extracted from prose SOPs. Existing installation steps below still apply.

### v0.49.5 — Reliable AI assignment previews

Assignment confirmations now recheck the previewed deadline, work type, sample, and primary project as well as status and assignee. Changed items are skipped with a request for a fresh preview; older previews without these details must also be regenerated. Requests above the 100-item assignment limit ask you to narrow the selection instead of silently taking the first 100. Requests naming multiple assignees ask for one assignee per action.

Work-operation requests with unsupported negation, date filters, or mixed actions ask for clarification instead of ignoring those conditions. Repeated project scopes and inactive assignees cannot produce assignment previews. Multi-project assignments retain their intended scope through confirmation. Work lists report the full matching count and explicitly disclose the 100-item display limit.

Work lists and assignment previews honor an explicitly named project. Unknown, inaccessible, or ambiguous project selections ask for an exact code or name instead of broadening the request. Assignment workload counts include only records visible to the requester; confirmation rejects work that moved out of the selected project. Combined overdue/unassigned filters and switching back to sample-status graphs are also corrected.

Work graphs accept polite requests and reversed metric order, and can show only overdue or only unassigned work. Removing the last selected record asks for a new selection instead of broadening the search. Explicit project selections in graph follow-ups replace the prior selection. Unassigned-work lists include overdue and undated items unless you explicitly request **today**. All reads continue to respect access permissions.

Fixes the bottleneck follow-up **Graph overdue and unassigned work**: it retains the selected project, charts current work counts, and no longer mistakes unassigned work for an assignment command.

Save named workflow questions to your account and reopen them from either chat view. Load a question into the builder, adjust it, then explicitly run it against current records. Only query settings are saved; permissions are checked again when running. Includes a 20-question limit and confirmed deletion. See the [saved questions guide](docs/assistant-project-workflows.md#personal-saved-questions).

### v0.48.0 — Build and reuse AI workflow questions

Use the **visual workflow query builder** in either chat view: choose a project, filters, AND/OR, assignee and scope, preview the question, then run it. Quick starts cover your overdue work, unassigned work due soon and QC problems. **Use the same filters in project CODE** transfers an existing query with fresh access checks and results from page one. English and Spanish supported. See the [builder and reuse guide](docs/assistant-project-workflows.md#build-and-reuse-workflow-questions).

### v0.47.0 — Understand your AI query

Use **Explain this query** to see filter meanings, AND/OR logic, scope, work ownership and current deadline windows. The bilingual explanation rechecks access, preserves pagination and performs no sample scan. Available in both chat views. See the [query explanation guide](docs/assistant-project-workflows.md#query-explanations).

**OpenLIMS** is an open-source, self-hosted Laboratory Information Management System built to support practical lab workflows such as sample tracking, project organization, collaborative experiment notebooks, inventory custody, internal workflow requests, instrument data ingestion, sequence analysis, local BLAST search, mass spectrometry review, legacy data migration, audit trails, reporting, role-based access control, and an assistant with optional OpenAI or local Ollama support that remains read-only unless a user explicitly confirms a supported action.

The project is designed as a lightweight, configurable, production-style foundation for research labs, small biotech teams, core facilities, and developer teams that need more structure than spreadsheets but do not want the cost or complexity of a traditional enterprise LIMS.

> **Status:** OpenLIMS is currently a production-style prototype. It is not yet a fully validated clinical, diagnostic, or regulated production LIMS.

**Current development version:** `v0.54.0 — Personal work priorities and conversational follow-ups`.

## Deployment Access

Hosted deployment addresses and access credentials are intentionally not
published in the repository. Authorized users should obtain access details
directly from the repository owner.

---

## ✨ Features

| Area | Capabilities |
|---|---|
| **My Work** | Unified assigned-work, workflow-request, experiment, QC, alert, notification, and overdue-work dashboard |
| **Samples** | Sample lifecycle tracking, aliquots and parent/child lineage, custody, statuses, attachments, custom fields, reason-for-change logging |
| **Pipelines** | Dependency graphs, parallel and conditional steps, optional work, controlled retries, project/sample-type defaults, assignment by sample/batch/project, failure blocking, QC gates |
| **Analyses & procedures** | Admin-configurable analysis types, required result schemas, versioned procedures, SOP links, expected duration |
| **Projects** | Project workspaces, project-scoped visibility, membership, cross-project sample linking, unified sample-to-report workflow view |
| **Notebook** | Scoped collaborative notebooks, block experiments, immutable revisions, comments, assignments, review/sign-off, locking, cloning, and provenance-rich PDF export |
| **Inventory** | Site-to-well location hierarchy, generic barcodes, plate maps, reagent/lot metadata, immutable scan ledger, reservations, alerts, and cycle-count reconciliation |
| **Workflow Requests** | Configurable internal assay forms, triage/approval, SLAs, pipeline assignment, resource reservation, batch/plate grouping, requester messages, execution status, and approved reports |
| **Imports** | Instrument CSV imports, flexible header detection, direct instrument/API ingestion |
| **Migration** | Legacy CSV migration profiles, reusable field mappings, preview/dry-run, queued imports, row review |
| **External IDs** | Preserve legacy sample IDs and aliases from older systems |
| **Sequences** | FASTA import workflows, sequence workspaces, sequence metadata and features |
| **Registry** | Configurable biological entity types, immutable versions, aliases, relationships, duplicate detection, review/registration, and physical-material links |
| **Molecular Biology** | Strict DNA/RNA/protein validation, circular topology, revision diff/restore, biochemical tools, virtual digests, construct assembly, feature libraries, and FASTA/GenBank interchange |
| **Alignments** | Clustal Omega alignment jobs with downloadable output |
| **BLAST** | Local BLAST database building and blastn/blastp search |
| **Mass Spec** | mzML, mzXML, mzData, featureXML, consensusXML, mzID/mzIdentML review using pyOpenMS |
| **Audit** | Audit events, barcode-scanned custody transfers, reason-for-change tracking, CSV exports |
| **Reports** | Project summaries, sample inventory, QC review, import summaries, audit activity, comparison and investigation CSV/PDF artifacts |
| **Visual analytics** | Investigation workbench, multi-sample/project/batch comparisons, result trends, outlier review, workflow bottlenecks, automatic charts |
| **Assistant** | OpenLIMS Rules, optional OpenAI or Ollama, clarification choices, visible removable context, investigation and comparison follow-ups, confirmed actions with expiring user-bound tokens and audit events |
| **Jobs** | Celery/Redis background jobs and real-time WebSocket updates |
| **Security** | HttpOnly browser JWT cookies, CSRF protection, refresh rotation/blacklisting, logout invalidation, role-based permissions, and Bearer JWT support for API clients |
| **Localization** | Director-controlled, instance-wide English or Spanish UI, including the sign-in screen and workflow pages |
| **Shared foundation** | Stable public IDs, reusable links and attachments, versioned APIs, OpenAPI documentation, common project permissions and audit payloads, and server-enforced guarded module feature flags |

---

## 🧭 Table of Contents

- [Installation](#installation)
- [Server deployment](#server-deployment)
- [Core Concepts](#-core-concepts)
- [OpenLIMS Assistant](#-openlims-assistant)
- [Architecture](#-architecture)
- [Permissions](#-permissions)
- [Local Development](#-local-development)
- [Optional Local Ollama Assistant](#-optional-local-ollama-assistant)
- [Testing](#-testing)
- [Deployment Notes](#-deployment-notes)
- [Current Project Status](#-current-project-status)
- [Roadmap](#-roadmap)

---

## 🧬 Core Concepts

### Samples

Samples are the central records in OpenLIMS. A sample can be assigned to a project, placed in a container, linked to results, connected to sequence records, used in BLAST or alignment workflows, associated with mass spectrometry runs, and connected to external IDs from legacy systems.

Supported sample statuses:

| Status |
|---|
| `RECEIVED` |
| `IN_PROGRESS` |
| `QC` |
| `REPORTED` |
| `ARCHIVED` |

OpenLIMS supports controlled status changes with a required reason for change, helping create a stronger chain-of-custody and audit trail.

### Projects

Projects act as shared workspaces for lab teams. They can contain samples, sequence workspaces, imports, BLAST jobs, alignments, mass spectrometry runs, notes, migration jobs, and project activity.

Project membership controls what non-admin users can see and modify.

### Cross-Project Sample Linking

A sample has one primary project, but it can also be linked to additional projects. This supports cases where a sample belongs to one study or team but needs to be visible to another project without transferring ownership.

```text
Sample: S-ALPHA-001
Primary Project: PRJ-ALPHA
Linked Projects: PRJ-BETA, PRJ-GAMMA
```

Linked projects provide visibility, while primary project ownership controls modification and import permissions.

### Sample Lineage and Chain of Custody

OpenLIMS records directed relationships between source and derived samples for
aliquots, splits, derived materials, and pooled components. Lineage links reject
self-links and cycles, retain the amount and unit when supplied, and require an
audited reason. A derived sample can be created directly from the Traceability
workspace while inheriting the source project, linked-project visibility, batch,
and applicable default workflow.

Barcode or sample-ID scans can record receipt, check-out, check-in, transfer,
storage movement, processing, and disposal. Each custody event preserves the
previous and new container and custodian, the operator, scan value, timestamp,
and handling reason. Disposal clears physical custody and archives the sample.

### Inventory

OpenLIMS models storage from a physical site down to an individual well:

```text
Site → Building → Laboratory → Room → Freezer → Shelf → Rack → Box → Well
```

Locations, containers, samples, reagent lots, and registered materials can have
generic barcode identities. Scanned operations create immutable transactions
for receive, move, transfer, count, consume, adjust, quarantine, disposal, and
return. Every quantity transaction records the actor, reason, unit, before and
after values, and linked experiment, request, or work item when supplied.

Inventory items and lots retain vendor, catalog, manufacturer, received/opened
and expiration dates, cost, storage conditions, chemical identity, hazards,
GHS classifications, SDS/COA files, and disposal guidance. Plate maps support
well-level placement, while reservations, expiration/reorder alerts, cycle
counts, and reconciliation keep available stock auditable.

---

## 📥 Instrument Imports

OpenLIMS supports CSV-based instrument imports and direct API ingestion.

Instrument profiles define:

- Instrument code and name
- Delimiter
- Sample ID column
- Column mappings
- Value types
- Numeric limits
- Allowed values
- Header row behavior
- Auto-detection of true CSV headers

### Flexible CSV Imports

Some instrument exports include metadata rows before the real CSV header. OpenLIMS can scan for the sample ID column and detect the actual header row.

```csv
Instrument,Example Analyzer
Run ID,RUN-001
Operator,Peter
sample_id,result,operator,qc_status
S-ALPHA-001,pass,Peter,PASS
```

---

## 🔁 Data Migration Toolkit

OpenLIMS includes a data migration toolkit for bringing legacy lab database exports into OpenLIMS in a safer, reviewable way.

```text
SISBI / legacy PostgreSQL, MySQL, SQLite, or CSV
   ↓
Migration profile
   ↓
Read-only datasets and field mapping
   ↓
Preview / dry run
   ↓
Confirm import
   ↓
Projects, inactive users, samples, metadata, work items, and historical results
```

The migration toolkit supports:

- Migration profiles
- Reusable field mappings
- Saved mapping templates that can be applied to another compatible profile
- CSV upload
- Director-managed read-only PostgreSQL, MySQL/MariaDB, and SQLite sources
- Schema/table inspection without arbitrary SQL
- Separate datasets for projects, users, samples, and historical results
- Preview / dry-run before import
- Required-field, data-type, relationship, status, and timestamp validation
- A source-and-mapping fingerprint that blocks a changed source after preview
- Per-job conflict policies: skip, merge blank fields, overwrite mapped fields, or create unique copies
- Project creation or matching
- Inactive user creation with unusable passwords and safe non-admin roles
- Sample creation or matching
- External sample IDs and aliases
- Custom field values
- Work items and results
- Migration job history
- Paginated migration row review
- Skipped/error row filtering
- CSV export for migration review
- Reconciliation reports with source, action, status, and entity totals
- Director-controlled rollback of tracked creations and updates

Database passwords are never stored in OpenLIMS. Configure the password in an
environment variable, enter only that variable's name in the connection, and
use a source account that has `SELECT` permission only. Remote hosts must also
be listed in `MIGRATION_DB_ALLOWED_HOSTS`. Each dataset has a row safety limit;
the final commit re-reads and fingerprints the source before writing anything.
Conflict policy is part of that fingerprint. Each committed job records the
objects it created and the original values it changed, allowing a director to
perform a guarded rollback. Rollback is blocked if later related data would be
put at risk.

### External Sample IDs and Aliases

OpenLIMS can preserve legacy identifiers from older databases or spreadsheets.

```text
Sample: S-UW-001
Source System: UW Legacy DB
Label: legacy_specimen_id
External ID: SP-00921
```

---

## 🤖 OpenLIMS Assistant

OpenLIMS includes an assistant for finding, explaining and summarizing accessible lab records. Supported changes use a preview and explicit confirmation before execution.

The assistant can help users ask questions such as:

- Show what needs attention across accessible lab work
- Find a sample by sample ID
- Summarize a project
- Show failed migration jobs
- Show skipped migration rows
- Explain why a migration job failed
- Identify the current logged-in OpenLIMS user

The assistant uses permission-checked backend tools as the source of truth. External models do not receive unrestricted database access. Workflow questions and query edits are read-only; supported lab changes are validated and executed by the backend only after confirmation.

The attention summary is permission-filtered and checks samples that have
remained in an active status for more than three days, missing sample
information, QC review states, aged open work items, failed instrument
imports, failed BLAST and alignment jobs, and admin-only system health
warnings. Inventory quantity, reservation, reorder, and expiry alerts are also
included when they need attention.

### Workflow questions and follow-ups

Start with an exact project code, then refine the question:

| Ask | Behavior |
|---|---|
| `Which samples in project DEMO-360 are overdue and unassigned on the same step?` | Both conditions must match one step of one pipeline run. |
| `Which samples in project DEMO-360 are assigned to me and overdue on the same step?` | Finds your assigned work with an overdue condition on that same step. |
| `Only assigned to maria` | Replaces the filters with one exact, active project username. |
| `Also assigned to me` | Adds your ownership to an AND query while preserving scope. |
| `Which samples in project DEMO-360 are assigned to me and due tomorrow on the same step?` | Finds your available work with a deadline tomorrow on that same step. |
| `Also due today` | Adds today’s deadline window to an AND query. |
| `Only due within 7 days` | Replaces the filters with deadlines in the next 168 hours. |
| `Match any condition` | Explicitly switches AND to OR while keeping the project and scope. |
| `Remove the overdue filter` | Removes that requirement; it does not exclude overdue samples. |
| `Across the sample` | Allows the conditions to match different steps or runs of a sample. |
| `Refresh results` | Rereads current records and permissions from page one. |

When there are no matches, the answer reports counts for each condition among the
samples checked in that request. Counts can overlap and must not be added. A
partial scan, including the last page of a paginated search, is not a complete
project total. If more samples remain, use `Next page` before concluding there
are no matches in the project. No active pipeline does not prove work is complete.

An unclear follow-up keeps the previous query only when its filters, scope and
project access remain valid. Recovery choices apply to that previous query, not
the rejected edit. Named assignees use exact, case-sensitive usernames of active
project members; `me` means the authenticated user. Only one assignee is supported
per query. Assigned work belongs to unfinished steps in active/blocked runs,
including QC-waiting work; it is not a claim that the assignee is a QC reviewer.
Use same-step scope when overdue/QC must apply to that person’s step. Mixed
AND/OR, negation, arbitrary dates and nested conditions remain unsupported. These bounded workflow routes work with OpenLIMS
Rules and do not require OpenAI or Ollama.

Deadline filters apply to available active work on ready/in-progress steps with
satisfied dependencies. Today and tomorrow are calendar days in the server’s
active timezone (UTC by default), shown with exact start/end timestamps in each
answer. Today can include already-overdue work from earlier today; the next seven
days begin now and cover 168 hours. Start is inclusive and end is exclusive.
Undated, completed/cancelled or dependency-blocked work does not match deadline
filters. Refresh and pagination use current dates and records, not a frozen snapshot.

### Assistant Modes

| Mode | Description |
|---|---|
| **OpenLIMS Rules** | Built-in rule-based search and summaries with no external model required |
| **OpenAI** | Optional external LLM summaries using server-side API configuration |
| **Ollama** | Optional local LLM summaries using a self-hosted Ollama container |

If an LLM is unavailable, the assistant falls back to **OpenLIMS Rules** mode.

The rules layer also handles common conversational requests such as greetings,
help, the current application date, and the current application time. If a
question is unrelated to OpenLIMS but can be answered conversationally, the
constrained route classifier can send it to a separate general-conversation
prompt. That prompt receives no database records or tool output and cannot run
an OpenLIMS action. Requests that appear to require unsupported laboratory data
or application operations remain explicit unsupported requests instead of being
answered as general chat.

The UI displays the active engine/model, such as:

```text
Using: OpenLIMS Rules
Using: OpenAI · gpt-5
Using: Ollama · llama3.2:1b
```

---

## 🧫 Sequence, BLAST, and Mass Spec Workflows

### Sequence Workspaces

Users can:

- Create sequence records
- Link sequences to samples and projects
- Store sequence metadata
- Add sequence features
- Import FASTA files
- Use sequences in alignment and BLAST workflows

```text
Sample → FASTA Import → Sequence Workspace → Alignment Job → BLAST Search
```

### Clustal Omega Alignments

OpenLIMS can queue Clustal Omega alignment jobs asynchronously. Alignment jobs store input FASTA, aligned FASTA, sequence count, alignment summary, status, and downloadable output.

### Local BLAST Search

OpenLIMS includes local BLAST support using NCBI BLAST+.

Users can:

- Upload FASTA files as local BLAST databases
- Build BLAST databases
- Run blastn searches
- Run blastp searches
- View parsed BLAST hits
- Inspect identity, e-value, rank, accession, and aligned regions

### Mass Spectrometry Workflows

OpenLIMS includes mass spectrometry support using pyOpenMS and OpenMS-compatible formats.

Supported workflows include:

- mzML, mzXML, and mzData upload
- featureXML parsing
- consensusXML parsing
- mzID / mzIdentML identification summaries
- TIC preview charts
- Spectra counts
- MS1/MS2 counts
- Retention time ranges
- m/z ranges
- Peak summaries
- Detected features
- Protein and peptide summaries
- Run comparison by project, sample, or manual selection

---

## 🧾 Audit Trail and Reports

OpenLIMS records important activity as audit events, including:

- Sample created
- Sample status changed
- Sample linked/unlinked from project
- Container assigned
- Attachment uploaded
- Results imported
- Migration imported
- FASTA imported
- Alignment queued or completed
- BLAST database built
- BLAST search completed
- Mass spec run uploaded or processed
- Settings changed

For controlled sample status changes, OpenLIMS records actor, before/after state, changed fields, reason for change, and timestamp.

Reports and CSV exports include:

- Project summaries
- Sample inventory
- QC review
- Import summaries
- Alignment summaries
- BLAST summaries
- Audit activity

---

## ⚡ Real-Time Job Updates

Background jobs run through Celery and Redis. OpenLIMS uses Django Channels and WebSockets to update the frontend when jobs change status.

Supported live-update workflows include:

- CSV imports
- Alignment jobs
- BLAST database builds
- BLAST searches
- Mass spec processing

---

## 🔐 Permissions

OpenLIMS uses role-based permissions and project-scoped access control. Browser sessions use HttpOnly JWT cookies with CSRF protection, refresh-token rotation, and logout invalidation. Bearer JWT authentication remains supported for scripts and non-browser API clients.

| Role | Purpose |
|---|---|
| **Admin / Director** | Full system access |
| **Tech** | Lab workflow access for assigned projects |
| **Viewer** | Read-only access |

### Sample Access Rules

| Role | Sample Visibility | Modify Samples |
|---|---|---|
| **Admin / Director** | All samples, including unassigned samples | Yes |
| **Tech** | Samples in assigned projects, linked project samples, and unassigned samples they created | Only samples they have modification rights for |
| **Viewer** | Samples in assigned or linked projects | No |

Linked-project access allows a user to see a sample, but it does not automatically grant edit or import permissions.

---

## 🏗 Architecture

| Layer | Technology |
|---|---|
| **Frontend** | React + Vite |
| **Production Web** | Nginx |
| **Backend API** | Django REST Framework |
| **Database** | PostgreSQL |
| **Background Jobs** | Celery |
| **Broker / Cache** | Redis |
| **Real-Time Updates** | Django Channels + Daphne |
| **Alignments** | Clustal Omega |
| **BLAST** | NCBI BLAST+ |
| **Mass Spec** | pyOpenMS |
| **Assistant** | OpenLIMS Rules, optional OpenAI, optional Ollama |
| **Reverse Proxy / TLS Edge** | Caddy or another trusted reverse proxy when used |
| **Deployment** | Docker Compose (development and production) |

High-level architecture:

```text
React Frontend / Production Nginx
   ↓
Django REST Framework API
   ↓
PostgreSQL

Redis
   ↓
Celery Worker
   ↓
Imports / Migrations / Alignments / BLAST / Mass Spec Jobs

Daphne + Django Channels
   ↓
WebSocket job updates

OpenLIMS Assistant
   ↓
Safe read-only backend tools
   ↓
Optional OpenAI or local Ollama summary
```

### Main Django Apps

| App | Responsibility |
|---|---|
| `samples` | Sample lifecycle, access control, attachments, transitions |
| `projects` | Projects, membership, project posts |
| `inventory` | Locations and containers |
| `imports` | Instrument profiles, CSV imports, direct instrument ingestion |
| `migration_toolkit` | Legacy CSV migration profiles, field mappings, dry-run previews, imports, and external IDs |
| `results` | Work items and structured results |
| `events` | Audit trail and audit export |
| `notifications` | User notifications |
| `custom_fields` | Configurable fields |
| `sequences` | Sequence records and features |
| `alignments` | Clustal Omega alignment jobs |
| `blast` | BLAST databases, jobs, and hits |
| `mass_spec` | Mass spec uploads, processing, summaries, and comparison |
| `settings_app` | Admin settings |
| `assistant` | Read-only assistant tools, OpenAI/Ollama summaries, and assistant status |
| `core` | Users, roles, permissions, search, shared utilities |

---

## Installation

### 1. Check what you need

Use a terminal on Linux or macOS, or an Ubuntu terminal in WSL2 on Windows. Install **Git**, **Docker with the Compose v2 plugin**, and **OpenSSL** first. Start Docker Desktop if you use it. These commands should succeed:

```bash
git --version
docker info
docker compose version
openssl version
```

This guide is for a **new installation on your own computer**, opened at **http://localhost:8080**. It builds the application from source and runs the frontend, API, database, and background worker in Docker. You do not need to install Python, Node.js, PostgreSQL, OpenAI, or Ollama separately. The first build downloads dependencies and can take several minutes.

For a shared lab server, also follow [Server deployment](#server-deployment). Do not overwrite an existing installation's environment file or database credentials.

### 2. Download OpenLIMS

```bash
git clone https://github.com/Mokey2002/OpenLIMS.git
cd OpenLIMS
cp deploy/.env.prod.example deploy/.env
chmod 600 deploy/.env
```

Run all remaining Docker commands from this **OpenLIMS folder**.

### 3. Set your local configuration

Run the following command **three times** to generate separate values for the Django secret, database password, and instrument key:

```bash
openssl rand -hex 32
```

Open `deploy/.env` in a text editor. Replace the existing values below; leave the other settings as they are. Replace each `REPLACE_...` placeholder with a generated value. Use the **same database password in both lines** that contain it.

```env
DJANGO_SECRET_KEY=REPLACE_DJANGO_SECRET
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080
OPENLIMS_PUBLIC_URL=http://localhost:8080
OPENLIMS_HTTP_PORT=8080

JWT_COOKIE_SECURE=false
CSRF_COOKIE_SECURE=false
SESSION_COOKIE_SECURE=false
SECURE_SSL_REDIRECT=false

POSTGRES_PASSWORD=REPLACE_DATABASE_PASSWORD
DATABASE_URL=postgres://openlims:REPLACE_DATABASE_PASSWORD@db:5432/openlims
INSTRUMENT_API_KEY=REPLACE_INSTRUMENT_KEY

OPENLIMS_ASSISTANT_LLM_ENABLED=false
OPENLIMS_EMAIL_ENABLED=false
```

The cookie settings above are for **local HTTP only**. Keep `POSTGRES_DB=openlims` and `POSTGRES_USER=openlims` from the template. Keep this file private; it contains your installation's secrets.

### 4. Build and start the application

```bash
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml up -d --build
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml ps
```

Wait for `db`, `redis`, and `api` to show healthy, and for `web` and `worker` to be running. The API applies database migrations and collects static files automatically. If it is still starting, check its progress:

```bash
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml logs --tail=80 api
```

### 5. Create your administrator account

```bash
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml exec api python manage.py createsuperuser
```

Choose your username, email, and password when prompted. Password characters are not displayed while you type. There is **no default administrator password**.

### 6. Sign in and check the installation

Open **http://localhost:8080** and sign in with the account you just created. Open **http://localhost:8080/api/health/** to check the API.

For an empty lab installation, you are ready to create your own projects and users. To explore connected example records instead, optionally run:

```bash
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml exec api python manage.py seed_demo
```

Use demo data only on an evaluation installation. It adds example records and enables the Registry and Notebook features. It does **not** create or change passwords: keep using your administrator account. New demo identities are non-login accounts.

### Stop and start again

Stop the installation without deleting its data:

```bash
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml stop
```

Start it again:

```bash
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml up -d
```

Database records and uploaded files are stored in Docker volumes. Keep the same Compose project name (`openlims`). **Do not use `down -v` to restart:** it removes the data volumes.

### Troubleshooting

| Problem | What to check |
|---|---|
| Cannot connect to Docker | Start Docker Desktop or ask your server administrator to grant Docker access. Confirm `docker info` works. |
| Port 8080 is already in use | Choose another `OPENLIMS_HTTP_PORT`, update both local origins and `OPENLIMS_PUBLIC_URL` to that port, then rerun the start command. |
| Page does not load or shows 502 | Check `ps` and the API logs above. The web service waits for a healthy API. |
| Login fails or returns CSRF 403 | Use the exact configured browser address. Local HTTP needs the three secure-cookie settings set to `false`. |
| Database authentication fails | The password in `DATABASE_URL` must match `POSTGRES_PASSWORD`. Changing the environment file does not reset a password in an existing database volume. |
| A dependency download fails | Check network access and retry the build. Do not delete the database or volumes to fix download errors. |

## Server deployment

For access from other computers, use your server's real hostname and a trusted HTTPS reverse proxy. Before starting the same stack:

- Set `DJANGO_ALLOWED_HOSTS` to the hostname, without a scheme or path. Include `127.0.0.1` for the internal API health check.
- Set `CSRF_TRUSTED_ORIGINS` and `OPENLIMS_PUBLIC_URL` to the browser's exact HTTPS address, including a nonstandard port if used.
- Set `JWT_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, and `SESSION_COOKIE_SECURE` to `true`. Keep `DJANGO_DEBUG=0`.
- Have the proxy preserve `Host`, send `X-Forwarded-Proto: https`, and forward WebSockets under `/ws/`. Restrict direct access to port 8080 to the proxy/trusted network.
- Arrange backups of the database, uploaded files, and private configuration before using real lab data.

Then follow steps 4–6 using your HTTPS address. SMTP and external AI are optional. See [Deployment Notes](#-deployment-notes) for more detail. The separate [guided installer](deploy/installer/README.md) is an initial implementation requiring published image digests; it is not needed for this source-based setup and is not an upgrade tool.

## 💻 Local Development

For editing source code with live reload, use this alternative **instead of** the installation stack above. Use a fresh checkout and environment file; do not replace an existing installation's configuration. You also need Node.js 22.12 or newer with npm (the locked Vite dependency also accepts Node.js 20.19–20.x).

```bash
cp deploy/.env.example deploy/.env
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.yml up -d --build db redis api worker
```

The development API runs migrations automatically. Once it is running, create an administrator:

```bash
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.yml exec api python manage.py createsuperuser
```

Start the frontend in a second terminal and leave it running:

```bash
cd frontend
npm ci
npm run dev
```

Open **http://localhost:5173**. The API is at **http://localhost:8000**, and Django admin is at **http://localhost:8000/admin/**. The development Compose file does not start a frontend container. Demo data is optional: run `seed_demo` using the development API service, then sign in with your own administrator account.

---

## 🦙 Optional Local Ollama Assistant

OpenLIMS can run the assistant with a local Ollama model instead of an external LLM provider.

Enable the assistant in `deploy/.env`:

```env
OPENLIMS_ASSISTANT_LLM_ENABLED=true
OPENLIMS_ASSISTANT_LLM_PROVIDER=ollama
OPENLIMS_ASSISTANT_LLM_ROUTING_ENABLED=true
OPENLIMS_ASSISTANT_LLM_ROUTING_MIN_CONFIDENCE=0.65
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama3.2:1b
OLLAMA_TIMEOUT_SECONDS=25
```

OpenLIMS first uses normalized deterministic routes. If no route matches, the
configured model may return a constrained, confidence-gated route hint from a
fixed allowlist. OpenLIMS then runs the normal permission checks, frozen
previews, and confirmation requirements. Invalid, low-confidence, or
unavailable model classifications fall back to an honest rule-based response.

Start the Ollama container:

```bash
docker compose -p openlims -f deploy/docker-compose.yml up -d ollama
```

Pull a small model:

```bash
docker compose -p openlims -f deploy/docker-compose.yml exec ollama ollama pull llama3.2:1b
```

Restart the API and frontend:

```bash
docker compose -p openlims -f deploy/docker-compose.yml restart api frontend
```

The Assistant page will show which engine is active: **OpenLIMS Rules**, **OpenAI**, or **Ollama**.

---

## 🧪 Testing

Run backend tests:

```bash
docker compose -p openlims -f deploy/docker-compose.yml exec api pytest -v
```

Run Django checks:

```bash
docker compose -p openlims -f deploy/docker-compose.yml exec api python manage.py check
```

Run frontend build:

```bash
cd frontend
npm ci
npm run build
```

Run Playwright browser tests after starting a testable OpenLIMS environment:

```bash
cd frontend/e2e
npm ci
npx playwright install chromium
npm test
```

The CI workflow also validates `makemigrations --check`, production Compose configuration, the production frontend build, secure-cookie authentication, CSRF behavior, `/api/v1/` browser traffic, workflow navigation, logout/session invalidation, and the v0.29 performance/pagination regressions.

---

## 🩺 Health Check

OpenLIMS includes a health endpoint:

```bash
curl http://localhost:8000/api/health/
```

The health check verifies:

- Database
- Redis/cache
- Clustal Omega
- blastn
- blastp
- makeblastdb
- pyOpenMS

---

## 🔖 Frontend Version Footer

The frontend footer should use the generated `frontend/src/version.js` file instead of a hardcoded version string.

Recommended footer source:

```jsx
OpenLIMS {OPENLIMS_VERSION}
```

The version file can be generated from the latest Git tag during frontend dev/build so the footer stays aligned with releases.

---

## 🚀 Deployment Notes

OpenLIMS can run locally, on a private lab server, on a VM, or on cloud infrastructure.

`deploy/docker-compose.prod.yml` provides the production-style stack introduced in v0.28.1. v0.29.0 improves runtime efficiency on that stack with reusable PostgreSQL connections, optional Redis-backed Django caching, gzip compression, immutable hashed-asset caching, route-level frontend code splitting, and larger bounded API pages. The production stack runs Django under Daphne, serves the built React frontend through Nginx, keeps PostgreSQL and Redis internal by default, persists database/cache/media/static data, includes health checks, and exposes the web service on `${OPENLIMS_HTTP_PORT:-8080}`. Ollama remains optional through the `llm` Compose profile.

For a new installation, follow the [installation steps](#installation) and [server configuration](#server-deployment), including administrator creation. Keep an existing installation's `deploy/.env`; do not copy the template over it. Use `--env-file deploy/.env` with the production Compose commands so the configured host port is read consistently.

A typical production-style deployment uses:

```text
Trusted TLS reverse proxy / load balancer (optional when TLS is terminated upstream)
   ↓
Nginx React frontend
   ↓
Django API / Daphne ASGI
   ↓
PostgreSQL

Redis
   ↓
Celery Worker
```

For real-time updates, the production web tier forwards WebSocket traffic under `/ws/*` to the Django/Daphne API service.

### Performance settings

The production environment template enables the recommended connection/cache settings:

```env
DB_CONN_MAX_AGE=60
CACHE_URL=redis://redis:6379/3
```

`DB_CONN_MAX_AGE` reuses healthy PostgreSQL connections instead of reconnecting for each request. Redis database 3 is reserved for Django application caching; Celery broker/results and Channels continue to use Redis databases 0, 1, and 2 respectively.

### Database Backup

Create a backup:

```bash
docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml exec -T db pg_dump -U openlims openlims > openlims_backup.sql
```

This command backs up the database only. Back up uploaded files and private configuration separately. Test restoration on an isolated installation, not over live laboratory data. On that isolated installation, restore the database with:

```bash
cat openlims_backup.sql | docker compose --env-file deploy/.env -p openlims -f deploy/docker-compose.prod.yml exec -T db psql -U openlims openlims
```

---

## 📌 Current Project Status

OpenLIMS is a production-style LIMS prototype with many production-shaped patterns already in place:

- Dockerized services
- PostgreSQL database
- Redis and Celery background jobs
- Django Channels real-time updates
- Unified My Work dashboard with bounded server-side summary aggregation
- Single-request application session bootstrap for user, feature flags, and unread-notification count
- Scalable API pagination with 50-row defaults and up to 200-row intentional collection pages
- Route-level React code splitting and production gzip/immutable asset caching
- Production PostgreSQL connection reuse and optional Redis-backed Django cache
- Targeted indexes for assigned-work and unread-notification hot paths
- Workflow-oriented Plan → Receive → Execute → Review → Report navigation
- HttpOnly browser JWT cookies with CSRF protection, refresh rotation/blacklisting, and logout invalidation
- Bearer JWT support for scripts and API clients
- Role-based permissions
- Project-scoped access control
- Backend-enforced Notebook and Registry feature flags
- Versioned `/api/v1/` browser traffic with compatibility routes
- Collaborative experiment notebooks and immutable revisions
- Inventory transaction ledger and cycle-count reconciliation
- Internal workflow request intake and resource reservation
- Cross-project sample linking
- Data migration toolkit
- External sample IDs and aliases
- Audit event logging
- Reason-for-change logging
- Upload validation
- CSV and FASTA import workflows
- Flexible CSV header detection
- Instrument profile mapping
- Sequence workspaces
- Clustal Omega integration
- Local BLAST integration
- pyOpenMS mass spectrometry workflows
- Reports
- Global search
- OpenLIMS Assistant
- Optional OpenAI assistant summaries
- Optional Docker-based local Ollama assistant
- Assistant engine/model indicator in the UI
- Admin settings
- Director-controlled English/Spanish interface
- System health checks
- Production Compose deployment and Nginx frontend image
- Backend, production-build, Compose, Playwright, and performance regression CI checks

Remaining production-readiness work includes:

- Formal data-retention and archive rules across laboratory records
- SSO and optional MFA
- External/S3-compatible file storage
- More formal backup and restore automation
- Monitoring and alerting
- Expanded regression and load coverage
- Validation-readiness documentation
- Formal regulated-environment validation package

---

## 🗺 Roadmap

Planned and future improvements include:

- Formal record-retention and archive controls instead of destructive deletion for laboratory records
- SSO and optional MFA
- More advanced migration support for multi-file exports and system-specific API connectors
- Plate layouts and multi-sample pooling calculations on top of lineage records
- More advanced QC approval workflows
- External file storage support
- Monitoring and alerting
- Validation-readiness documentation
- Assistant calculations for safe counts, averages, percentages, and summaries
- Continued query-count, large-dataset, workflow, reporting, and browser performance regression improvements

See [`docs/performance_scalability_v029.md`](docs/performance_scalability_v029.md) for the v0.29.0 performance and scalability implementation notes and [`docs/product_hardening_v0281.md`](docs/product_hardening_v0281.md) for the v0.28.1 product-hardening notes.

---

## 🎯 Project Goals

OpenLIMS aims to be:

- Lightweight
- Self-hosted
- Configurable
- Open source and extensible for laboratory-specific workflows and integrations
- Practical for real lab workflows
- Easy to run locally or on low-cost cloud infrastructure
- Useful for small labs, research groups, and biotech teams
- A strong foundation for lab workflow automation

---

## 👤 Author

**Eduardo L**

LinkedIn: https://www.linkedin.com/in/edlemus/

---

## 📄 License

Copyright © 2026 Eduardo Lemus.

OpenLIMS is open-source software licensed under the
[Apache License 2.0](LICENSE). You may use, modify, and distribute the source
code in accordance with the license terms.

Third-party dependencies and bundled components remain subject to their own
licenses. See [`docs/licensing_history.md`](docs/licensing_history.md) for the
project's licensing history.
