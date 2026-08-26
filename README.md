# 🧪 OpenLIMS

<p align="center">
  <strong>Open-source, self-hosted Laboratory Information Management System for practical lab workflows.</strong>
</p>

<p align="center">
  <a href="#-features">Features</a>
  ·
  <a href="#-architecture">Architecture</a>
  ·
  <a href="#-local-development">Local Development</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-v0.26.0-blue">
  <img alt="License" src="https://img.shields.io/badge/license-Apache%202.0-green">
  <img alt="Backend" src="https://img.shields.io/badge/backend-Django%20REST%20Framework-darkgreen">
  <img alt="Frontend" src="https://img.shields.io/badge/frontend-React%20%2B%20Vite-61DAFB">
  <img alt="Database" src="https://img.shields.io/badge/database-PostgreSQL-336791">
  <img alt="Assistant" src="https://img.shields.io/badge/assistant-OpenLIMS%20%7C%20OpenAI%20%7C%20Ollama-purple">
</p>

---

## Overview

**OpenLIMS** is an open-source, self-hosted Laboratory Information Management System built to support practical lab workflows such as sample tracking, project organization, inventory storage, instrument data ingestion, sequence analysis, local BLAST search, mass spectrometry review, legacy data migration, audit trails, reporting, role-based access control, and an assistant with optional OpenAI or local Ollama support that remains read-only unless a user explicitly confirms a supported action.

The project is designed as a lightweight, configurable, production-style foundation for research labs, small biotech teams, core facilities, and developer teams that need more structure than spreadsheets but do not want the cost or complexity of a traditional enterprise LIMS.

> **Status:** OpenLIMS is currently a production-style prototype. It is not yet a fully validated clinical, diagnostic, or regulated production LIMS.

**Current release:** `v0.26.0 — Registry and Molecular Biology v2`

### v0.26.0 highlights

- Configurable biological registry types with versioned JSON schemas and stable registry IDs
- Immutable registry versions, aliases, external identifiers, tags, typed relationships, and project visibility
- Draft, review, registration, and retirement lifecycle with director approval and common audit payloads
- Duplicate detection across IDs, aliases, sequence checksums, catalog numbers, and configured schema fields
- Registry CSV and legacy-database migration through the existing preview/fingerprint/commit toolkit
- Strict DNA, RNA, and protein validation with linear/circular topology and immutable sequence revisions
- Revision diff/restore, reverse complement, transcription, translation, ORFs, GC, molecular weight, and primer calculations
- Restriction-site analysis, virtual digests, simple construct assembly plans, and reusable feature libraries
- Annotation-preserving FASTA and GenBank import/export and registry-linked sequence revisions
- English and Spanish Registry and molecular-biology interfaces

### v0.25.1 highlights

- Stable public UUIDs for projects, samples, sequences, inventory objects, and pipeline runs without replacing existing numeric API IDs
- Versioned `/api/v1/` routes with an initial OpenAPI schema and interactive documentation
- Reusable entity links and file attachments addressed by entity type and public ID
- Shared project-scoped permission helpers and a versioned audit-event payload contract
- Director-controlled, default-off feature flags for Notebook, Registry, Studies, and Insight
- Build-time enforcement of English and Spanish metadata for new feature-flagged modules
- Compatibility coverage keeping existing `/api/` routes available during the versioning transition

### v0.25.0 highlights

- Ask a focused clarification question instead of guessing when a request has multiple valid meanings
- Offer semantic choices for ambiguous QC sample/result, general sample/result, failure, and inventory requests
- Preserve the current conversation context while the user chooses a clarification option
- Show the active investigation, comparison, BLAST setup, sample, result, batch, or inventory context in both assistant interfaces
- Let users clear retained context before asking an unrelated follow-up
- Keep clarification prompts rule-based so OpenAI or Ollama cannot rewrite the available choices

### v0.24.3 highlights

- Prevent retained investigation, comparison, and BLAST context from capturing unrelated questions
- Distinguish samples in QC, samples needing QC review, and samples with failed QC results
- Return concise QC worklists without automatic graphs or LLM rewriting
- Require focused investigation follow-ups and show charts only for explicit visualization requests
- Keep notification language, SOP questions, and analytical comparisons within their intended domains
- Prevent LLM summaries from generalizing findings to unlisted records
- Seed eleven realistic instrument runs with direct sample, work-item, and result provenance
- Upgrade existing demo databases idempotently when `seed_demo` is run again
- Link connector-created work items directly to their originating instrument import job
- Expose instrument code, instrument name, run ID, source type, and import job on work-item and result APIs
- Backfill legacy connector work items from the established `Import Job <id>` naming convention
- Preserve audit/text fallback behavior for older records that cannot be linked automatically
- Show direct instrument/run provenance beside results and work items on the sample page
- Show linked sample, work-item, and result counts on each import job
- Use the database relation as the highest-confidence instrument provenance in investigations
- Keep provenance immutable through regular work-item and result APIs

---

## Deployment Access

Hosted deployment addresses and access credentials are intentionally not
published in the repository. Authorized users should obtain access details
directly from the repository owner.

---

## ✨ Features

| Area | Capabilities |
|---|---|
| **Samples** | Sample lifecycle tracking, aliquots and parent/child lineage, custody, statuses, attachments, custom fields, reason-for-change logging |
| **Pipelines** | Dependency graphs, parallel and conditional steps, optional work, controlled retries, project/sample-type defaults, assignment by sample/batch/project, failure blocking, QC gates |
| **Analyses & procedures** | Admin-configurable analysis types, required result schemas, versioned procedures, SOP links, expected duration |
| **Projects** | Project workspaces, project-scoped visibility, membership, cross-project sample linking, unified sample-to-report workflow view |
| **Inventory** | Locations, containers, sample placement |
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
| **Security** | JWT authentication and role-based permissions |
| **Localization** | Director-controlled, instance-wide English or Spanish UI, including the sign-in screen and workflow pages |
| **Shared foundation** | Stable public IDs, reusable links and attachments, versioned APIs, OpenAPI documentation, common project permissions and audit payloads, and guarded module feature flags |

---

## 🧭 Table of Contents

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

OpenLIMS supports basic storage organization:

```text
Location → Container → Sample
```

Example:

```text
Freezer A → BOX-A1 → S-ALPHA-001
Fridge B  → BOX-B1 → S-BETA-001
```

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

OpenLIMS includes a read-only assistant for quickly finding and summarizing records inside the system.

The assistant can help users ask questions such as:

- Show what needs attention across accessible lab work
- Find a sample by sample ID
- Summarize a project
- Show failed migration jobs
- Show skipped migration rows
- Explain why a migration job failed
- Identify the current logged-in OpenLIMS user

The assistant uses safe backend tools as the source of truth. It does **not** directly modify database records.

The attention summary is permission-filtered and checks samples that have
remained in an active status for more than three days, missing sample
information, QC review states, aged open work items, failed instrument
imports, failed BLAST and alignment jobs, and admin-only system health
warnings. Inventory quantity and expiry alerts remain unavailable until those
values are represented in the inventory schema.

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

OpenLIMS uses JWT authentication and role-based permissions.

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
| **Backend API** | Django REST Framework |
| **Database** | PostgreSQL |
| **Background Jobs** | Celery |
| **Broker / Cache** | Redis |
| **Real-Time Updates** | Django Channels + Daphne |
| **Alignments** | Clustal Omega |
| **BLAST** | NCBI BLAST+ |
| **Mass Spec** | pyOpenMS |
| **Assistant** | OpenLIMS Rules, optional OpenAI, optional Ollama |
| **Reverse Proxy** | Caddy |
| **Deployment** | Docker Compose |

High-level architecture:

```text
React Frontend
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

## 💻 Local Development

### 1. Clone the repository

```bash
git clone https://github.com/Mokey2002/OpenLIMS.git
cd OpenLIMS
```

### 2. Create the environment file

```bash
cp deploy/.env.example deploy/.env
```

Example local environment:

```env
DJANGO_DEBUG=1
DJANGO_SECRET_KEY=dev-secret-key
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

POSTGRES_DB=openlims
POSTGRES_USER=openlims
POSTGRES_PASSWORD=openlims
DB_HOST=db
DB_PORT=5432

CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
CHANNEL_REDIS_URL=redis://redis:6379/2

INSTRUMENT_API_KEY=my-shared-lab-instrument-key

OPENLIMS_ASSISTANT_LLM_ENABLED=false
OPENLIMS_ASSISTANT_LLM_PROVIDER=ollama
OPENLIMS_ASSISTANT_LLM_ROUTING_ENABLED=true
OPENLIMS_ASSISTANT_LLM_ROUTING_MIN_CONFIDENCE=0.65
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama3.2:1b
OLLAMA_TIMEOUT_SECONDS=25
```

### 3. Start services

```bash
docker compose -p openlims -f deploy/docker-compose.yml up -d --build
```

### 4. Run migrations

```bash
docker compose -p openlims -f deploy/docker-compose.yml exec api python manage.py migrate
```

### 5. Seed demo data

```bash
docker compose -p openlims -f deploy/docker-compose.yml exec api python manage.py seed_demo
```

The command is idempotent and seeds connected demonstrations for projects,
samples, batches, custom metadata, lineage, barcode custody, inventory,
reservations, workflows, results, QC, instrument imports, migration previews and
rollback, Registry records, Molecular Biology revisions and assembly plans,
BLAST, alignments, mass spectrometry, reports, notifications, audit history,
shared links and attachments, and assistant confirmations. Set
`OPENLIMS_DEMO_PASSWORD` before running it to enable sign-in for the demo users;
otherwise newly created demo accounts have unusable passwords.

The Registry feature flag is enabled for the comprehensive demo. Notebook,
Studies, and Insight remain disabled because those modules are still under
development.

### 6. Open the app

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| API | http://localhost:8000 |
| Admin | http://localhost:8000/admin |
| Health | http://localhost:8000/api/health/ |

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
npm install
npm run build
```

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

A typical production-style deployment uses:

```text
Caddy Reverse Proxy
   ↓
React Static Frontend
   ↓
Django API / Daphne ASGI
   ↓
PostgreSQL

Redis
   ↓
Celery Worker
```

For real-time updates, the production reverse proxy should forward WebSocket traffic under `/ws/*` to the Django/Daphne API service.

### Database Backup

Create a backup:

```bash
docker compose -p openlims -f deploy/docker-compose.prod.yml exec db pg_dump -U openlims openlims > openlims_backup.sql
```

Restore a backup:

```bash
cat openlims_backup.sql | docker compose -p openlims -f deploy/docker-compose.prod.yml exec -T db psql -U openlims openlims
```

---

## 📌 Current Project Status

OpenLIMS is a production-style LIMS prototype with many production-shaped patterns already in place:

- Dockerized services
- PostgreSQL database
- Redis and Celery background jobs
- Django Channels real-time updates
- JWT authentication
- Role-based permissions
- Project-scoped access control
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
- CI checks

Remaining production-readiness work includes:

- External/S3-compatible file storage
- More formal backup and restore automation
- Monitoring and alerting
- Expanded regression coverage
- Secure production settings review
- Validation-readiness documentation
- Formal regulated-environment validation package

---

## 🗺 Roadmap

Planned and future improvements include:

- More advanced migration support for multi-file exports and system-specific API connectors
- Plate layouts and multi-sample pooling calculations on top of lineage records
- More advanced QC approval workflows
- Better dashboards for lab operations
- External file storage support
- Monitoring and alerting
- Validation-readiness documentation
- Assistant calculations for safe counts, averages, percentages, and summaries
- Confirmed assistant actions with explicit user approval

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
