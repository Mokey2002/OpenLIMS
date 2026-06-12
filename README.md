# OpenLIMS

OpenLIMS is a lightweight, modular, production-style Laboratory Information Management System (LIMS) designed to support real laboratory workflows such as sample tracking, project organization, inventory storage, instrument data ingestion, sequence workspaces, Clustal Omega alignments, local BLAST search, mass spectrometry preview workflows, audit trails, notifications, reporting, real-time job updates, and system health monitoring.

OpenLIMS is currently a production-style prototype, not a fully validated clinical or regulated production LIMS. The goal is to provide a practical, configurable, easy-to-deploy foundation for laboratory workflow software.

---

## Live Demo

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

## Current Release

# OpenLIMS v0.11.0 — pyOpenMS Mass Spectrometry Preview

OpenLIMS v0.11.0 adds an initial mass spectrometry module powered by pyOpenMS. Users can upload mass spectrometry files, process them asynchronously through Celery, view extracted run metadata, inspect MS1/MS2 spectrum counts, and preview a Total Ion Chromatogram (TIC) chart from retention time and total intensity data.

### v0.11.0 Highlights

- New Mass Spec module
- Upload support for `mzML`, `mzXML`, and `mzData` files
- pyOpenMS-based file processing
- Celery background processing for mass spec runs
- Mass spec run list page
- Mass spec run detail page
- Total Ion Chromatogram (TIC) preview chart
- Chromatogram point table
- Spectra count extraction
- MS1/MS2 spectrum count extraction
- Retention time range extraction
- m/z range extraction
- Project and sample linking for mass spec runs
- Reprocess action for uploaded mass spec runs
- Audit events for upload, processing, reprocessing, and failure states
- pyOpenMS health check support
- Docker runtime dependencies for pyOpenMS
- Backend permission tests for mass spec upload, read, and reprocess access

### Access Control

| Role | Mass Spec Access |
|---|---|
| Admin / Director | Upload, view, reprocess |
| Tech | Upload, view, reprocess |
| Viewer | View only |

### Supported Mass Spec Workflow

```text
Upload mzML / mzXML / mzData file
   ↓
Create MassSpecRun as PENDING
   ↓
Queue Celery processing task
   ↓
pyOpenMS loads experiment
   ↓
Extract spectra count, MS1/MS2 counts, RT range, m/z range, TIC points
   ↓
Store results on MassSpecRun
   ↓
Render Mass Spec detail page and TIC chart
   ↓
Record audit events
```

---

## Core Features

## Role-Based Access Control

OpenLIMS uses JWT authentication and role-based permissions.

| Role | Purpose |
|---|---|
| Admin / Director | Full administrative access |
| Tech | Lab workflow access |
| Viewer | Read-only access |

Director/admin users can manage users, system settings, instrument profiles, imports, samples, sequences, projects, audit workflows, reports, and system health tools.

Tech users can perform lab workflow actions such as updating samples, running imports, managing sequence workspaces, queueing alignments, running BLAST searches, and processing mass spec runs.

Viewer users can inspect dashboards, samples, projects, audit events, imports, sequences, alignments, BLAST results, mass spec runs, and reports without write access.

---

## Sample Management

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
- Link samples to sequence workspaces, import jobs, BLAST jobs, and mass spec runs

---

## Project Management

Projects act as shared workspaces for lab teams.

Users can:

- Create projects
- Assign users to projects
- Restrict visibility by project membership
- Add project notes and feed posts
- Link samples, imports, sequences, alignments, BLAST jobs, and mass spec runs to projects
- Notify project members when updates are posted

---

## Inventory Management

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

## Sequence Workspaces

OpenLIMS includes sequence workspace support for DNA, RNA, and protein records.

Users can:

- Create sequence workspaces
- Link sequences to samples
- Link sequences to projects
- Store sequence metadata
- View sequence features such as annotations, primers, translations, and highlights
- Import FASTA records into sequence workspaces
- Use sequence records as inputs for Clustal Omega alignments and BLAST searches

Example workflow:

```text
Sample → FASTA import → Sequence workspace → Alignment job → BLAST search → Audit event
```

---

## FASTA Import Preview and Confirm

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

## Instrument Data Ingestion

OpenLIMS supports two ingestion workflows:

- CSV upload through the UI
- Direct instrument/API push

Instrument profiles define how incoming data should be interpreted. Each instrument profile can define an instrument name, instrument code, delimiter, sample ID column, column mappings, numeric min/max validation, and allowed values.

Demo instrument profiles include:

- NovaFlex Analyzer
- Illumina MiSeq Sequencer
- Applied Biosystems 3500 Sanger Sequencer
- Charles River Endosafe Nexus
- Molecular Devices SpectraMax Plate Reader
- Applied Biosystems 7500 qPCR System
- Thermo Fisher NanoDrop One
- Agilent 2100 Bioanalyzer
- Hamilton STAR Liquid Handler
- Generic FASTA Sequencer

---

## Async Import Processing

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

Import jobs track status, source type, run ID, progress, rows processed, samples created or matched, results created, skipped rows, and linked samples.

---

## Real-Time Job Updates

OpenLIMS includes real-time job updates using Django Channels, Daphne, Redis Pub/Sub, and JWT-authenticated WebSocket connections.

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

The BLAST, Alignments, and Imports pages show live update status badges. Users can still click Refresh manually, but normal job completion no longer requires manual refresh.

---

## Clustal Omega Alignments

OpenLIMS supports sequence alignment jobs using Clustal Omega. Alignment jobs run asynchronously through Celery and store input FASTA, aligned FASTA, sequence count, alignment summary, and downloadable aligned FASTA. Alignment status and completion update live through WebSockets.

---

## Local BLAST Search

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
| Query Sequence | BLAST Demo Query |
| BLAST Database | Demo DNA BLAST DB |
| Program | `blastn` |

### BLAST APIs

```text
GET  /api/blast-databases/
POST /api/blast-databases/
POST /api/blast-databases/:id/build/
GET  /api/blast-jobs/
POST /api/blast-jobs/
GET  /api/blast-jobs/:id/hits/
```

---

## Mass Spectrometry Preview

OpenLIMS v0.11.0 introduces mass spectrometry preview support using pyOpenMS.

Users can:

- Upload `mzML`, `mzXML`, and `mzData` files
- Link mass spec runs to projects
- Link mass spec runs to samples
- Process files asynchronously using Celery
- View run status and processing errors
- Reprocess uploaded runs
- View spectra counts
- View MS1/MS2 counts
- View retention time range
- View m/z range
- View a TIC chart
- View raw chromatogram points
- View audit events for mass spec workflows

### Mass Spec APIs

```text
GET  /api/mass-spec-runs/
POST /api/mass-spec-runs/
GET  /api/mass-spec-runs/:id/
POST /api/mass-spec-runs/:id/reprocess/
```

### TIC Preview

The TIC chart is generated from each spectrum by summing intensity values and plotting total intensity against retention time.

```text
Spectrum RT + intensity values
   ↓
Sum intensities per spectrum
   ↓
Store chromatogram_data
   ↓
Render SVG TIC chart in React
```

---

## Analysis

The analysis page supports selecting projects, selecting samples, choosing numeric result metrics, viewing trends over time, and exporting chart data as CSV.

This helps users inspect imported results such as concentration, purity, yield, qPCR Ct values, MiSeq Q-scores, endotoxin values, and plate reader absorbance.

---

## Reports

OpenLIMS includes a reports page for operational summaries and CSV exports.

Current report areas include:

- Project summary
- Sample inventory
- QC review
- Import summary
- Alignment summary
- BLAST summary
- Audit activity

---

## Global Search

OpenLIMS includes a global search endpoint and navbar search experience.

Search can return:

- Samples
- Projects
- Sequences
- Alignments
- BLAST databases
- BLAST jobs
- BLAST hits
- Import jobs
- Instruments
- Events
- Users for admin users

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

## Audit Trail and Chain of Custody Foundation

OpenLIMS records important actions as audit events.

Examples include:

- Sample created
- Sample status changed
- Sample container changed
- Attachment uploaded
- Results imported
- Import retry queued
- Sequence imported
- Alignment queued
- Alignment completed
- BLAST database built
- BLAST job completed
- Mass spec uploaded
- Mass spec processed
- Mass spec reprocess queued
- Mass spec failed
- Settings updated
- Settings reset to defaults

The Events page supports audit export as CSV and JSON. Audit logs can be filtered by entity type, action, actor, search term, and date range.

---

## Notifications

OpenLIMS includes notifications for key activity such as:

- Import completed
- Import failed
- Project post created
- Sequencing review needed
- Endotoxin review needed
- Alignment completed
- Alignment failed
- BLAST job completed
- BLAST job failed
- Demo environment seeded

---

## Admin Settings

OpenLIMS includes an admin/director settings page for system-level configuration.

Settings include:

- Lab name
- Organization name
- Default timezone
- Default sample status
- Import settings
- FASTA extension settings
- Sequence/alignment limits
- Security settings such as viewer read-only mode and audit reason requirements

Settings changes are logged to the audit event log.

---

## System Status Dashboard

OpenLIMS includes a system status dashboard and health endpoint.

The health endpoint checks important runtime dependencies:

- Database
- Redis/cache
- Clustal Omega
- `blastn`
- `blastp`
- `makeblastdb`
- pyOpenMS

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
  "makeblastdb_ok": true,
  "pyopenms_ok": true,
  "pyopenms_version": "..."
}
```

---

## Architecture

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

### Mass Spec Processing

```text
Celery Worker
   ↓
pyOpenMS
   ↓
MassSpecRun summary + TIC data
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
Clustal Omega + BLAST+ + pyOpenMS

Daphne ASGI
   ↓
Django Channels WebSockets
   ↓
Redis Pub/Sub
```

---

## Services

| Service | Purpose |
|---|---|
| React + Vite | Frontend UI |
| Django REST Framework | API and business logic |
| Daphne | ASGI runtime for HTTP and WebSocket traffic |
| PostgreSQL | Primary database |
| Redis | Celery broker/result backend and WebSocket channel layer |
| Celery Worker | Background imports, alignments, BLAST jobs, mass spec processing, and real-time job broadcasts |
| Clustal Omega | Sequence alignment engine |
| NCBI BLAST+ | Local BLAST database and search engine |
| pyOpenMS | Mass spectrometry file parsing and preview processing |
| Caddy | Reverse proxy and static file serving |
| Docker Compose | Service orchestration |

---

## Main Django Apps

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
| `mass_spec` | Mass spectrometry uploads, pyOpenMS processing, TIC preview |
| `settings_app` | Admin system settings |
| `core` | Users, roles, permissions, search, shared utilities |

---

## Import Workflows

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

## Authentication and Permissions

OpenLIMS uses:

- JWT authentication for users
- Shared API key authentication for instrument ingestion
- Role-based API permissions
- Backend permission tests

| Role | Demo User | Access |
|---|---|---|
| Director/Admin | `director` | Full system access |
| Tech | `peter`, `maria`, `michael` | Lab workflow access |
| Viewer | `viewer` | Read-only access |

Backend tests help verify that viewer users cannot perform write actions such as creating samples, updating samples, creating sequence workspaces, running imports, creating alignment jobs, creating BLAST databases, building BLAST databases, creating BLAST jobs, uploading mass spec files, reprocessing mass spec runs, changing system settings, or managing users.

---

## Local Development

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
```

Production deployment note: OpenLIMS real-time updates require the API container to run Daphne/ASGI and the reverse proxy to forward `/ws/*` to the API service.

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

## Testing Mass Spec Locally

You can generate a small demo mzML file inside the API container:

```bash
docker compose -p openlims -f deploy/docker-compose.yml exec -T api python - <<'PY'
import math
import random
import pyopenms as oms

exp = oms.MSExperiment()
random.seed(42)

for i in range(30):
    spectrum = oms.MSSpectrum()
    ms_level = 1 if i % 5 != 0 else 2
    spectrum.setMSLevel(ms_level)
    spectrum.setRT(5.0 + i * 2.5)

    peak_shape = math.exp(-((i - 15) ** 2) / 45.0)
    mz_values = []
    intensities = []

    for j in range(20):
        mz_values.append(100.0 + j * 25.0 + random.random())
        intensity = (1000.0 * peak_shape) + random.uniform(10.0, 80.0)
        if ms_level == 2:
            intensity *= 0.45
        intensities.append(intensity)

    spectrum.set_peaks((mz_values, intensities))
    exp.addSpectrum(spectrum)

oms.MzMLFile().store("/app/media/demo_curve_mass_spec.mzML", exp)
print("/app/media/demo_curve_mass_spec.mzML")
PY
```

Copy it locally:

```bash
docker cp openlims-api:/app/media/demo_curve_mass_spec.mzML ./demo_curve_mass_spec.mzML
```

Upload it from the Mass Spec page:

```text
http://localhost:5173/mass-spec
```

Expected result:

```text
Spectra: 30
MS1: 24
MS2: 6
TIC Points: 30
```

---

## Running Tests

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

Test coverage includes instrument API ingest, CSV import workflow, duplicate run protection, import retry validation, FASTA import validation, backend permissions, project permissions, sample transitions, notifications, alignment workflow behavior, BLAST permission tests, mass spec permission tests, and system health checks.

---

## CI/CD

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

## Database Backup

Create backup:

```bash
docker compose -p openlims -f deploy/docker-compose.prod.yml exec db pg_dump -U openlims openlims > openlims_backup.sql
```

Restore backup:

```bash
cat openlims_backup.sql | docker compose -p openlims -f deploy/docker-compose.prod.yml exec -T db psql -U openlims openlims
```

---

## Enterprise Feature Roadmap

| # | Feature | Status |
|---|---|---|
| 1 | Admin Settings page | Added |
| 2 | Audit log export | Added |
| 3 | User management improvements | Added |
| 4 | QC approval workflow | Added |
| 5 | Project dashboard | Added |
| 6 | Bulk sample actions | Added |
| 7 | Reports page | Added |
| 8 | System status dashboard | Added |
| 9 | Global search | Added |
| 10 | FASTA sequence workflows | Added |
| 11 | Clustal Omega alignments | Added |
| 12 | Local BLAST search | Added |
| 13 | Real-time background job updates | Added |
| 14 | pyOpenMS mass spectrometry preview | Added |
| 15 | Sample Detail mass spec integration | Planned |
| 16 | Peak picking and feature detection | Planned |
| 17 | Reason-for-change audit logging | Planned |
| 18 | S3/external media storage | Planned |
| 19 | Validation-readiness documentation | Planned |
| 20 | Monitoring and alerting | Planned |

---

## Production Readiness Status

OpenLIMS is currently best described as a production-style open-source LIMS prototype.

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
- pyOpenMS integration
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

## Planned for v0.12.0

- Sample Detail mass spec integration
- Peak picking
- Feature detection
- Consensus maps
- Protein/peptide ID summaries
- mzIdentML support
- FeatureXML/consensusXML parsing
- Quality metrics
- Sample comparison
- Stronger chain-of-custody workflows

---

## Project Goals

OpenLIMS aims to be:

- Lightweight
- Deployable
- Configurable
- Open-source friendly
- Production-shaped
- Useful for real lab workflows
- Easy to run locally or on low-cost cloud infrastructure
- A strong foundation for research lab workflow automation

---

## Author

Eduardo L  
LinkedIn: https://www.linkedin.com/in/edlemus/

---

## License

Apache 2.0
