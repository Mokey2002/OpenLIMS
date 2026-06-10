# 🧪 OpenLIMS

**OpenLIMS** is a lightweight, modular, production-style Laboratory Information Management System (LIMS) designed to support real lab workflows such as sample tracking, project organization, inventory storage, instrument data ingestion, sequence workspaces, Clustal Omega alignments, local BLAST search, audit trails, notifications, reporting, and system health monitoring.

OpenLIMS is currently a **production-style prototype**, not a fully validated clinical or regulated production LIMS. The goal is to provide a practical, configurable, easy-to-deploy foundation for laboratory workflow software.

---

## 🌐 Live Demo

OpenLIMS is currently deployed here:

```text
http://16.146.193.92
```

### Demo Users

| User | Password | Role |
|---|---|---|
| `director` | `Director123!` | Admin / director access |
| `peter` | `peter123` | Lab tech access |
| `maria` | `maria123` | Lab tech access |
| `michael` | `michael123` | Lab tech access |
| `viewer` | `viewer123` | Read-only access |

---

## 🚀 Current Release

**OpenLIMS v0.9.0 — Real-Time Job Updates**

This release adds real-time WebSocket job updates across OpenLIMS background workflows. BLAST jobs, Clustal Omega alignment jobs, and CSV import jobs can now update the frontend automatically without relying on manual refresh or page-level polling.

### v0.9.0 Highlights

- Django Channels WebSocket foundation
- Daphne ASGI runtime for HTTP and WebSocket traffic
- Redis Pub/Sub channel layer for real-time broadcasts
- JWT-authenticated WebSocket connections
- Shared backend broadcast utility for job updates
- Live BLAST database and BLAST job updates
- Live Clustal Omega alignment job updates
- Live CSV import progress and completion updates
- Frontend real-time job socket hook
- Live update indicators on BLAST, Alignments, and Imports pages
- Import page cleanup: removed active-job polling and improved paginated profile loading
- Instrument profile dropdown fix for newly created profiles

---

## 🚀 Core Features

### Role-Based Access Control

OpenLIMS uses JWT authentication and role-based permissions.

Current roles:

| Role | Purpose |
|---|---|
| `admin` / Director | Full administrative access |
| `tech` | Lab workflow access |
| `viewer` | Read-only access |

Director/admin users can manage users, system settings, instrument profiles, imports, samples, sequences, projects, audit workflows, reports, and system health tools.

Tech users can perform lab workflow actions such as updating samples, running imports, managing sequence workspaces, queueing alignments, and running BLAST searches.

Viewer users can inspect dashboards, samples, projects, audit events, imports, sequences, alignments, BLAST results, and reports without write access.

---

## 🧫 Sample Management

OpenLIMS supports sample lifecycle tracking with statuses such as:

- `RECEIVED`
- `IN_PROGRESS`
- `QC`
- `REPORTED`
- `ARCHIVED`

Users can:

- Create and track samples
- Assign samples to projects
- Assign samples to containers and storage locations
- Upload sample attachments
- View sample work items, results, and audit timeline events
- Link samples to sequence workspaces and import jobs

---

## 📁 Project Management

Projects act as shared workspaces for lab teams.

Users can:

- Create projects
- Assign users to projects
- Restrict visibility by project membership
- Add project notes/feed posts
- Link samples, imports, sequences, alignments, and BLAST jobs to projects
- Notify project members when updates are posted

---

## 🧊 Inventory Management

OpenLIMS supports basic lab inventory organization:

- Storage locations
- Containers
- Container-to-location assignment
- Sample-to-container assignment

Example structures:

```text
Freezer A → BOX-A1 → S-ALPHA-001
Fridge B  → BOX-B1 → S-BETA-001
Sequencing Bench → SEQ-RACK-1 → S-GAMMA-001
```

---

## 🧬 Sequence Workspaces

OpenLIMS includes sequence workspace support for DNA, RNA, and protein records.

Users can:

- Create sequence workspaces
- Link sequences to samples
- Link sequences to projects
- Store sequence metadata
- View sequence features such as annotations, primers, translations, and highlights
- Import FASTA records into sequence workspaces
- Use sequence records as inputs for Clustal Omega alignments and BLAST searches

Sequence workspaces are designed to support workflows like:

```text
Sample → FASTA import → Sequence workspace → Alignment job → BLAST search → Audit event
```

---

## 🧬 FASTA Import Preview and Confirm

OpenLIMS supports a safer FASTA import workflow:

```text
Upload FASTA
   ↓
Preview records
   ↓
Show matched samples
   ↓
Show unmatched records
   ↓
Confirm import
   ↓
Create sequence workspaces
```

The preview step helps prevent accidental bad imports by showing records found, matched samples, unmatched samples, records that will create sequence workspaces, and skipped records.

---

## 🧪 Instrument Data Ingestion

OpenLIMS supports two ingestion workflows:

1. CSV upload through the UI
2. Direct instrument/API push

Instrument profiles define how incoming data should be interpreted. Each instrument profile can define an instrument name, instrument code, delimiter, sample ID column, column mappings, numeric min/max validation, and allowed values.

Demo instrument profiles include NovaFlex Analyzer, Illumina MiSeq Sequencer, Applied Biosystems 3500 Sanger Sequencer, Charles River Endosafe Nexus, Molecular Devices SpectraMax Plate Reader, Applied Biosystems 7500 qPCR System, Thermo Fisher NanoDrop One, Agilent 2100 Bioanalyzer, Hamilton STAR Liquid Handler, and Generic FASTA Sequencer.

---

## ⚙️ Async Import Processing

CSV imports are processed asynchronously using Celery and Redis.

```text
User uploads CSV
   ↓
Django API creates ImportJob as PENDING
   ↓
Django queues Celery task in Redis
   ↓
Celery worker processes CSV rows
   ↓
Worker updates ImportJob progress
   ↓
Worker creates samples, work items, and results
   ↓
Worker marks job COMPLETED or FAILED
```

Import jobs track status, source type, run ID, progress, rows processed, samples created/matched, results created, skipped rows, and linked samples.

---

## ⚡ Real-Time Job Updates

OpenLIMS v0.9.0 adds real-time job updates using Django Channels, Daphne, Redis Pub/Sub, and JWT-authenticated WebSocket connections.

Supported live workflows:

- CSV import jobs
- Clustal Omega alignment jobs
- BLAST database build jobs
- BLAST search jobs

Real-time flow:

```text
Celery Worker updates job state
   ↓
Backend broadcasts job update
   ↓
Redis Pub/Sub channel layer
   ↓
Django Channels WebSocket consumer
   ↓
React page receives update
   ↓
Frontend reloads current job data automatically
```

The BLAST, Alignments, and Imports pages show a live update status badge. Users can still click Refresh manually, but normal job completion no longer requires manual refresh.

---

## 🧬 Async Clustal Omega Alignments

OpenLIMS supports sequence alignment jobs using Clustal Omega. Alignment jobs run asynchronously through Celery and store input FASTA, aligned FASTA, sequence count, alignment summary, and downloadable aligned FASTA. Alignment status and completion now update live through WebSockets.

---

## 🔎 Local BLAST Search

OpenLIMS includes a local BLAST workflow for sequence similarity searches.

Users can:

- Upload FASTA files as local BLAST databases
- Build BLAST databases using `makeblastdb`
- Run nucleotide BLAST searches with `blastn`
- Run protein BLAST searches with `blastp`
- Queue BLAST jobs asynchronously through Celery
- View BLAST job status with live updates
- View parsed BLAST hits
- Inspect identity, e-value, rank, accession, and aligned regions
- Use seeded demo data for quick testing

### BLAST Demo Workflow

After running `seed_demo`, users can test BLAST with:

| Field | Value |
|---|---|
| Query Sequence | `BLAST Demo Query` |
| BLAST Database | `Demo DNA BLAST DB` |
| Program | `blastn` |

The seeded database includes a known matching reference so users can confirm that the BLAST workflow is working.

### BLAST APIs

- `GET /api/blast-databases/`
- `POST /api/blast-databases/`
- `POST /api/blast-databases/:id/build/`
- `GET /api/blast-jobs/`
- `POST /api/blast-jobs/`
- `GET /api/blast-jobs/:id/hits/`

### BLAST Integration Points

BLAST is integrated into the BLAST page, System Status dashboard, Global Search, Reports page, CSV report export, backend permission tests, demo seed data, and Docker image dependencies.

---

## 📊 Analysis

The analysis page supports selecting projects, selecting samples, choosing numeric result metrics, viewing trends over time, and exporting chart data as CSV.

This helps users inspect imported results such as concentration, purity, yield, qPCR Ct values, MiSeq Q-scores, endotoxin values, and plate reader absorbance.

---

## 📈 Reports

OpenLIMS includes a reports page for operational summaries and CSV exports.

Current report areas include:

- Project summary
- Sample inventory
- QC review
- Import summary
- Alignment summary
- BLAST summary
- Audit activity

The BLAST summary includes total BLAST databases, ready BLAST databases, total BLAST jobs, completed BLAST jobs, failed BLAST jobs, total BLAST hits, recent BLAST jobs, and BLAST CSV export.

---

## 🔍 Global Search

OpenLIMS includes a global search endpoint and navbar search experience.

Search can return samples, projects, sequences, alignments, BLAST databases, BLAST jobs, BLAST hits, import jobs, instruments, events, and users for admin users.

Example searches:

```text
S-ALPHA
GFP
BLAST
Demo DNA
blastn
BLAST_REF_ALPHA
NovaFlex
```

---

## 🧾 Audit Trail and Chain of Custody

OpenLIMS records important actions as audit events.

Examples include sample created, sample status changed, sample container changed, attachment uploaded, results imported, import retry queued, sequence imported, alignment queued, alignment completed, BLAST database built, BLAST job completed, settings updated, and settings reset to defaults.

The Events page supports audit export as CSV and JSON. Audit logs can be filtered by entity type, action, actor, search term, and date range.

---

## 🔔 Notifications

OpenLIMS includes notifications for key activity such as import completed, import failed, project post created, sequencing review needed, endotoxin review needed, alignment completed, alignment failed, BLAST job completed, BLAST job failed, and demo environment seeded.

---

## 🛠 Admin Settings

OpenLIMS includes an admin/director settings page for system-level configuration.

Settings include lab name, organization name, default timezone, default sample status, import settings, FASTA extension settings, sequence/alignment limits, and security settings such as viewer read-only mode and audit reason requirements.

Settings changes are logged to the audit event log.

---

## 🩺 System Status Dashboard

OpenLIMS includes a system status dashboard and health endpoint.

The health endpoint checks important runtime dependencies:

- Database
- Redis/cache
- Clustal Omega
- `blastn`
- `blastp`
- `makeblastdb`

Example:

```bash
curl http://localhost:8000/api/health/
```

Example response:

```json
{
  "status": "ok",
  "db_ok": true,
  "redis_ok": true,
  "clustalo_ok": true,
  "blastn_ok": true,
  "blastp_ok": true,
  "makeblastdb_ok": true
}
```

---

## 🧱 Architecture

### Application Architecture

```text
React + Vite Frontend
   ↓
Django REST Framework API
   ↓
PostgreSQL
```

### Real-Time Architecture

```text
React WebSocket Client
   ↓
Daphne ASGI Server
   ↓
Django Channels Consumer
   ↓
Redis Pub/Sub Channel Layer
   ↓
Celery job update broadcasts
```

### Async Processing

```text
Django API
   ↓
Redis
   ↓
Celery Worker
   ↓
PostgreSQL
```

### Alignment Processing

```text
Celery Worker
   ↓
Clustal Omega
   ↓
AlignmentJob result
```

### BLAST Processing

```text
Celery Worker
   ↓
NCBI BLAST+
   ↓
BlastJob + BlastHit results
```

### Production Runtime Architecture

```text
Internet
   ↓
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
   ↓
Clustal Omega + BLAST+

Daphne ASGI
   ↓
Django Channels WebSockets
   ↓
Redis Pub/Sub
```

---

## 🧩 Services

| Service | Purpose |
|---|---|
| React + Vite | Frontend UI |
| Django REST Framework | API and business logic |
| Daphne | ASGI runtime for HTTP and WebSocket traffic |
| PostgreSQL | Primary database |
| Redis | Celery broker/result backend and WebSocket channel layer |
| Celery Worker | Background imports, alignments, BLAST jobs, and real-time job broadcasts |
| Clustal Omega | Sequence alignment engine |
| NCBI BLAST+ | Local BLAST database and search engine |
| Caddy | Reverse proxy and static file serving |
| Docker Compose | Service orchestration |

---

## 🗂️ Main Django Apps

| App | Responsibility |
|---|---|
| `samples` | Sample lifecycle, transitions, attachments |
| `projects` | Projects, membership, posts |
| `inventory` | Locations and containers |
| `imports` | Instrument profiles, mappings, import jobs |
| `results` | Work items and structured results |
| `events` | Audit trail and audit export |
| `notifications` | User alerts |
| `custom_fields` | Configurable fields |
| `sequences` | Sequence workspaces and features |
| `alignments` | Clustal Omega alignment jobs |
| `blast` | BLAST databases, jobs, and hits |
| `settings_app` | Admin system settings |
| `core` | Users, roles, permissions, search, shared utilities |

---

## 🔁 Import Workflows

### CSV Upload Workflow

```text
Frontend Import Page
   ↓
POST /api/import-jobs/
   ↓
ImportJob created with PENDING status
   ↓
process_import_job.delay(job.id)
   ↓
Redis queues the task
   ↓
Celery worker processes CSV rows
   ↓
Samples, work items, and results are created
   ↓
ImportJob summary is updated
```

### FASTA Import Workflow

```text
Frontend Import Page
   ↓
Upload FASTA
   ↓
POST /api/import-jobs/sequence-fasta-preview/
   ↓
Preview matched/unmatched records
   ↓
Confirm import
   ↓
POST /api/import-jobs/sequence-fasta-import/
   ↓
Sequence workspaces created
   ↓
Events logged
```

### Instrument API Push Workflow

```text
Instrument / Adapter Script
   ↓
POST /api/import-jobs/instrument-ingest/
   ↓
API key validated
   ↓
Instrument profile loaded
   ↓
Rows validated and processed
   ↓
Samples, work items, and results are created
   ↓
ImportJob marked COMPLETED
```

Example request:

```bash
curl -X POST http://localhost:8000/api/import-jobs/instrument-ingest/ \
  -H "Content-Type: application/json" \
  -H "X-Instrument-Api-Key: my-shared-lab-instrument-key" \
  -d '{
    "instrument_code": "NOVAFLEX",
    "run_id": "RUN-001",
    "rows": [
      {
        "sample_id": "S-001",
        "concentration": 12.4,
        "purity": 97.1,
        "qc_flag": "PASS"
      }
    ]
  }'
```

---

## 🔐 Authentication and Permissions

OpenLIMS uses JWT authentication for users, shared API key authentication for instrument ingestion, role-based API permissions, and backend permission tests.

| Role | Demo User | Access |
|---|---|---|
| Director/Admin | `director` | Full system access |
| Tech | `peter`, `maria`, `michael` | Lab workflow access |
| Viewer | `viewer` | Read-only access |

Backend tests help verify that viewer users cannot perform write actions such as creating samples, updating samples, creating sequence workspaces, running imports, creating alignment jobs, creating BLAST databases, building BLAST databases, creating BLAST jobs, changing system settings, or managing users.

---

## 🐳 Local Development

### 1. Clone the repository

```bash
git clone https://github.com/Mokey2002/OpenLIMS.git
cd OpenLIMS
```

### 2. Create environment file

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

INSTRUMENT_API_KEY=my-shared-lab-instrument-key
Production deployment note:
OpenLIMS real-time updates require the API container to run Daphne/ASGI and the reverse proxy to forward `/ws/*` to the API service.
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

### 6. Create superuser if needed

```bash
docker compose -p openlims -f deploy/docker-compose.yml exec api python manage.py createsuperuser
```

### 7. Open app

```text
Frontend: http://localhost:5173
API:      http://localhost:8000
Admin:    http://localhost:8000/admin
Health:   http://localhost:8000/api/health/
```

---

## 🧪 Running Tests

Run all tests:

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

Test coverage includes instrument API ingest, CSV import workflow, duplicate run protection, import retry validation, FASTA import validation, backend permissions, project permissions, sample transitions, notifications, alignment workflow behavior, BLAST permission tests, and system health checks. Real-time job update behavior can be verified locally by queueing BLAST, alignment, and import jobs and confirming the frontend updates without manual refresh.

---

## ✅ CI/CD

OpenLIMS uses GitHub Actions for CI.

Typical CI flow:

```text
Push / Pull Request
   ↓
Build Docker services
   ↓
Run Django checks
   ↓
Check migrations
   ↓
Run migrations
   ↓
Run pytest
   ↓
Install frontend dependencies
   ↓
Build frontend
```

---

## 📦 Database Backup

Create backup:

```bash
docker compose -p openlims -f deploy/docker-compose.prod.yml exec db pg_dump -U openlims openlims > openlims_backup.sql
```

Restore backup:

```bash
cat openlims_backup.sql | docker compose -p openlims -f deploy/docker-compose.prod.yml exec -T db psql -U openlims openlims
```

---

## 🏢 Enterprise Feature Roadmap

| # | Feature | Status |
|---|---|---|
| 1 | Admin Settings page | ✅ Added |
| 2 | Audit log export | ✅ Added |
| 3 | User management improvements | ✅ Added |
| 4 | QC approval workflow | ✅ Added |
| 5 | Project dashboard | ✅ Added |
| 6 | Bulk sample actions | ✅ Added |
| 7 | Reports page | ✅ Added |
| 8 | System status dashboard | ✅ Added |
| 9 | Global search | ✅ Added |
| 10 | FASTA sequence workflows | ✅ Added |
| 11 | Clustal Omega alignments | ✅ Added |
| 12 | Local BLAST search | ✅ Added |
| 13 | Real-time background job updates | ✅ Added |
| 14 | Reason-for-change audit logging | Planned |
| 15 | S3/external media storage | Planned |
| 16 | Validation-readiness documentation | Planned |
| 17 | Monitoring and alerting | Planned |

---

## 🔒 Production Readiness Status

OpenLIMS is currently best described as:

```text
Production-style open-source LIMS prototype
```

It includes several production-shaped patterns:

- Dockerized services
- PostgreSQL database
- Redis + Celery async jobs
- Django Channels + WebSocket live job updates
- Role-based access control
- Audit event logging
- Audit log export
- Health checks
- Upload validation
- CI tests
- Frontend build checks
- Admin settings
- User management
- QC approval workflow
- Reports
- System status dashboard
- Global search
- AWS deployment
- Clustal Omega integration
- BLAST+ integration
- Daphne ASGI runtime

Remaining production-readiness work:

- Reason-for-change enforcement on critical edits
- S3 or external file storage
- Formal backup/restore procedures
- Monitoring and alerting
- Secure production settings review
- Expanded permission and regression coverage
- Validation-readiness documentation
- Formal regulated-environment validation package

---

## 📌 Project Goals

OpenLIMS aims to be lightweight, deployable, configurable, open-source friendly, production-shaped, useful for real lab workflows, easy to run locally or on low-cost cloud infrastructure, and a strong foundation for research lab workflow automation.

---

## 👨‍💻 Author

**Eduardo L**  
LinkedIn: https://www.linkedin.com/in/edlemus/

---

## 📄 License

Apache 2.0
