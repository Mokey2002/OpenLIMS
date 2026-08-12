# 🧪 OpenLIMS

<p align="center">
  <strong>Self-hosted Laboratory Information Management System for practical lab workflows.</strong>
</p>

<p align="center">
  <a href="#-features">Features</a>
  ·
  <a href="#-architecture">Architecture</a>
  ·
  <a href="#-local-development">Local Development</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-v0.23.0-blue">
  <img alt="License" src="https://img.shields.io/badge/license-proprietary-red">
  <img alt="Backend" src="https://img.shields.io/badge/backend-Django%20REST%20Framework-darkgreen">
  <img alt="Frontend" src="https://img.shields.io/badge/frontend-React%20%2B%20Vite-61DAFB">
  <img alt="Database" src="https://img.shields.io/badge/database-PostgreSQL-336791">
  <img alt="Assistant" src="https://img.shields.io/badge/assistant-OpenLIMS%20%7C%20OpenAI%20%7C%20Ollama-purple">
</p>

---

## Overview

**OpenLIMS** is a self-hosted Laboratory Information Management System built to support practical lab workflows such as sample tracking, project organization, inventory storage, instrument data ingestion, sequence analysis, local BLAST search, mass spectrometry review, legacy data migration, audit trails, reporting, role-based access control, and an assistant with optional OpenAI or local Ollama support that remains read-only unless a user explicitly confirms a supported action.

The project is designed as a lightweight, configurable, production-style foundation for research labs, small biotech teams, core facilities, and developer teams that need more structure than spreadsheets but do not want the cost or complexity of a traditional enterprise LIMS.

> **Status:** OpenLIMS is currently a production-style prototype. It is not yet a fully validated clinical, diagnostic, or regulated production LIMS.

**Current release:** `v0.23.0 — Investigation Workbench`

### v0.23.0 highlights

- Investigate a sample or result from a dedicated workbench or a natural-language Assistant request
- Rank direct, comparative, and contextual findings with visible severity and confidence
- Compare failed measurements with same-batch or same-project peers using transparent statistics
- Review workflow delays, overdue work, similar QC failures, and the audit timeline together
- Trace instrument-connector results back to their import job through existing work-item provenance
- Review project/time-window instrument and reagent evidence without presenting association as causation
- Graph failure rates by analyte, result entrant, or work type, plus instrument and reagent context
- Export a recalculated, permission-checked evidence package as audited CSV or PDF
- Keep calculations deterministic and permission-filtered; OpenAI or Ollama is optional

---

## Deployment Access

Hosted deployment addresses and access credentials are intentionally not
published in the repository. Authorized users should obtain access details
directly from the repository owner.

---

## ✨ Features

| Area | Capabilities |
|---|---|
| **Samples** | Sample lifecycle tracking, statuses, attachments, custom fields, reason-for-change logging |
| **Projects** | Project workspaces, project-scoped visibility, project membership, cross-project sample linking |
| **Inventory** | Locations, containers, sample placement |
| **Imports** | Instrument CSV imports, flexible header detection, direct instrument/API ingestion |
| **Migration** | Legacy CSV migration profiles, reusable field mappings, preview/dry-run, queued imports, row review |
| **External IDs** | Preserve legacy sample IDs and aliases from older systems |
| **Sequences** | FASTA import workflows, sequence workspaces, sequence metadata and features |
| **Alignments** | Clustal Omega alignment jobs with downloadable output |
| **BLAST** | Local BLAST database building and blastn/blastp search |
| **Mass Spec** | mzML, mzXML, mzData, featureXML, consensusXML, mzID/mzIdentML review using pyOpenMS |
| **Audit** | Audit events, reason-for-change tracking, CSV exports |
| **Reports** | Project summaries, sample inventory, QC review, import summaries, audit activity, comparison and investigation CSV/PDF artifacts |
| **Visual analytics** | Investigation workbench, multi-sample/project/batch comparisons, result trends, outlier review, workflow bottlenecks, automatic charts |
| **Assistant** | OpenLIMS Rules, optional OpenAI or Ollama, investigation and comparison follow-ups, confirmed actions with expiring user-bound tokens and audit events |
| **Jobs** | Celery/Redis background jobs and real-time WebSocket updates |
| **Security** | JWT authentication and role-based permissions |

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
Legacy database export
   ↓
CSV upload
   ↓
Migration profile
   ↓
Field mapping
   ↓
Preview / dry run
   ↓
Confirm import
   ↓
Projects, samples, external IDs, custom fields, work items, and results created
```

The migration toolkit supports:

- Migration profiles
- Reusable field mappings
- CSV upload
- Preview / dry-run before import
- Project creation or matching
- Sample creation or matching
- External sample IDs and aliases
- Custom field values
- Work items and results
- Migration job history
- Paginated migration row review
- Skipped/error row filtering
- CSV export for migration review

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
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama3.2:1b
OLLAMA_TIMEOUT_SECONDS=25
```

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

- More advanced migration support for multi-file exports and direct database imports
- Expanded relationship tracking for derived samples
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
- Extensible for future open-core or commercial deployment models
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

Copyright © 2026 Eduardo Lemus. All rights reserved.

The current OpenLIMS source code is proprietary. Unauthorized copying,
modification, distribution, or use is prohibited without prior written
permission from the copyright owner. See [`LICENSE`](LICENSE) for the current
terms.

Earlier OpenLIMS releases that were explicitly distributed under Apache
License 2.0 remain governed by the terms applicable to those releases. The
final Apache-licensed snapshot is recorded as `v0.22.0-apache-final` at commit
`ade352491f8824d5599f8cfaee01adec011f959e`. See
[`docs/licensing_history.md`](docs/licensing_history.md) for the cutoff record.
