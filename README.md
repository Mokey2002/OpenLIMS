# 🧪 OpenLIMS

OpenLIMS is a lightweight, modular, production-style **Laboratory Information Management System (LIMS)** designed to support real lab workflows such as sample tracking, project organization, inventory storage, instrument data ingestion, sequence workspaces, audit trails, notifications, result analysis, and alignment workflows.

OpenLIMS is currently a **production-style prototype**, not a fully validated clinical or regulated production LIMS. The goal is to provide a practical, configurable, easy-to-deploy foundation for laboratory workflow software.

---

## 🌐 Live Demo

OpenLIMS is currently deployed here:

```text
http://16.146.193.92
```

### Demo Users

```text
director / Director123!   Admin/director access
peter    / peter123       Lab tech access
maria    / maria123       Lab tech access
michael  / michael123     Lab tech access
viewer   / viewer123      Read-only access
```

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

Director/admin users can manage users, system settings, instrument profiles, imports, samples, sequences, projects, and audit workflows.

Tech users can perform lab workflow actions such as updating samples, running imports, managing sequence workspaces, and queueing alignments.

Viewer users can inspect dashboards, samples, projects, audit events, imports, sequences, and alignments without write access.

---

### Sample Management

OpenLIMS supports sample lifecycle tracking with statuses such as:

```text
RECEIVED
IN_PROGRESS
QC
REPORTED
ARCHIVED
```

Users can:

- Create and track samples
- Assign samples to projects
- Assign samples to containers and storage locations
- Upload sample attachments
- View sample work items, results, and audit timeline events
- Link samples to sequence workspaces and import jobs

---

### Project Management

Projects act as shared workspaces for lab teams.

Users can:

- Create projects
- Assign users to projects
- Restrict visibility by project membership
- Add project notes/feed posts
- Link samples, imports, sequences, and alignments to a project
- Notify project members when updates are posted

Demo project feed data includes multiple users posting on the same project, such as director, Peter, Maria, Michael, and viewer accounts.

---

### Inventory Management

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

Sequence workspaces are designed to support workflows like:

```text
Sample → FASTA import → Sequence workspace → Alignment job → Audit event
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

The preview step helps prevent accidental bad imports by showing:

- Records found
- Matched samples
- Unmatched samples
- Records that will create sequence workspaces
- Skipped records

---

## 🧪 Instrument Data Ingestion

OpenLIMS supports two ingestion workflows:

1. CSV upload through the UI
2. Direct instrument/API push

Instrument profiles define how incoming data should be interpreted.

Each instrument profile can define:

- Instrument name
- Instrument code
- Delimiter
- Sample ID column
- Column mappings
- Numeric min/max validation
- Allowed values

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

## ⚙️ Async Import Processing

CSV imports are processed asynchronously using **Celery** and **Redis**.

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

Import jobs track:

- Status
- Source type
- Run ID
- Progress current
- Progress total
- Progress message
- Rows processed
- Samples created
- Samples matched
- Results created
- Skipped rows
- Linked samples

Supported status flow:

```text
PENDING → RUNNING → COMPLETED
                  ↘ FAILED
```

---

## 🧬 Async Clustal Omega Alignments

OpenLIMS supports sequence alignment jobs using **Clustal Omega**.

Alignment jobs run asynchronously through Celery:

```text
User selects 2+ sequence workspaces
   ↓
Django API creates AlignmentJob as PENDING
   ↓
Celery worker runs Clustal Omega
   ↓
Job updates to RUNNING
   ↓
Aligned FASTA is stored
   ↓
Job updates to COMPLETED or FAILED
   ↓
User receives notification
```

The frontend polls active jobs and shows:

```text
PENDING → RUNNING → COMPLETED / FAILED
```

Alignment results include:

- Input FASTA
- Aligned FASTA
- Sequence count
- Alignment summary
- Downloadable aligned FASTA
- Color-coded alignment preview

---

## 📊 Analysis

The analysis page supports:

- Selecting projects
- Selecting samples
- Choosing numeric result metrics
- Viewing trends over time
- Exporting chart data as CSV

This helps users inspect imported results such as:

- Concentration
- Purity
- Yield
- qPCR Ct values
- MiSeq Q-scores
- Endotoxin values
- Plate reader absorbance

---

## 🧾 Audit Trail and Chain of Custody

OpenLIMS records important actions as audit events.

Examples:

- Sample created
- Sample status changed
- Sample container changed
- Attachment uploaded
- Results imported
- Import retry queued
- Sequence imported
- Alignment queued
- Alignment completed
- Settings updated
- Settings reset to defaults

Audit events can include before/after values:

```json
{
  "before": {
    "status": "RECEIVED"
  },
  "after": {
    "status": "IN_PROGRESS"
  },
  "changed_fields": ["status"]
}
```

### Audit Log Export

The Events page supports audit export:

```text
Export CSV
Export JSON
```

Audit logs can be filtered by:

- Entity type
- Action
- Actor
- Search term
- Date range

This is one of the enterprise-style features added to support governance and traceability.

---

## 🔔 Notifications

OpenLIMS includes notifications for key activity:

- Import completed
- Import failed
- Project post created
- Sequencing review needed
- Endotoxin review needed
- Alignment completed
- Alignment failed
- Demo environment seeded

---

## 🛠 Admin Settings

OpenLIMS includes an admin/director settings page for system-level configuration.

Settings include:

### General Settings

- Lab name
- Organization name
- Default timezone
- Default sample status

### Import Settings

- Max upload size
- Require import preview
- Allowed FASTA extensions

### Sequence and Alignment Settings

- Enable alignment jobs
- Max sequences per alignment
- Max sequence length

### Security Settings

- Viewer read-only mode
- Require audit reason for critical changes

Settings changes are logged to the audit event log.

---

## 🧱 Architecture

```text
React + Vite Frontend
   ↓
Django REST Framework API
   ↓
PostgreSQL

Async processing:
Django API
   ↓
Redis
   ↓
Celery Worker
   ↓
PostgreSQL

Alignment processing:
Celery Worker
   ↓
Clustal Omega
   ↓
AlignmentJob result
```

### Production Runtime Architecture

```text
Internet
   ↓
Caddy Reverse Proxy
   ↓
React Static Frontend
   ↓
Django API / Gunicorn
   ↓
PostgreSQL

Redis
   ↓
Celery Worker
   ↓
Clustal Omega
```

### Services

| Service | Purpose |
|---|---|
| React + Vite | Frontend UI |
| Django REST Framework | API and business logic |
| PostgreSQL | Primary database |
| Redis | Celery broker/result backend |
| Celery Worker | Background imports and alignments |
| Clustal Omega | Sequence alignment engine |
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
| `settings_app` | Admin system settings |
| `core` | Users, roles, permissions, shared utilities |

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

OpenLIMS uses:

- JWT authentication for users
- Shared API key authentication for instrument ingestion
- Role-based API permissions
- Backend permission tests

Current roles:

| Role | Demo User | Access |
|---|---|---|
| Director/Admin | `director` | Full system access |
| Tech | `peter`, `maria`, `michael` | Lab workflow access |
| Viewer | `viewer` | Read-only access |

Backend tests help verify that viewer users cannot perform write actions.

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
Health:   http://localhost:8000/health/
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

Test coverage includes:

- Instrument API ingest
- CSV import workflow
- Duplicate run protection
- Import retry validation
- FASTA import validation
- Backend permissions
- Project permissions
- Sample transitions
- Notifications
- Alignment workflow behavior

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

## 🩺 Health Checks

The health endpoint checks important runtime dependencies:

```text
Database
Redis/cache
Clustal Omega
```

Example:

```bash
curl http://localhost:8000/health/
```

Example response:

```json
{
  "status": "ok",
  "db_ok": true,
  "redis_ok": true,
  "clustalo_ok": true
}
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

## 🚀 AWS Deployment Notes

After merging to `main`:

```bash
ssh ubuntu@16.146.193.92
cd ~/OpenLIMS

git checkout main
git pull origin main

docker compose -p openlims -f deploy/docker-compose.prod.yml up -d --build api worker
docker compose -p openlims -f deploy/docker-compose.prod.yml exec api python manage.py migrate
docker compose -p openlims -f deploy/docker-compose.prod.yml exec api python manage.py check

cd frontend
npm install
npm run build

cd ~/OpenLIMS
docker compose -p openlims -f deploy/docker-compose.prod.yml restart caddy
```

Seed demo data on AWS:

```bash
docker compose -p openlims -f deploy/docker-compose.prod.yml exec api python manage.py seed_demo
```

---

## 🏢 Enterprise Feature Roadmap

These are the enterprise-style OpenLIMS features being implemented in order:

| # | Feature | Status |
|---|---|---|
| 1 | Admin Settings page | ✅ Added |
| 2 | Audit log export | ✅ Added |
| 3 | User management improvements | In progress |
| 4 | QC approval workflow | Planned |
| 5 | Project dashboard | Planned |
| 6 | Bulk sample actions | Planned |
| 7 | Reports page | Planned |
| 8 | System status dashboard | Planned |

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
- Role-based access control
- Audit event logging
- Audit log export
- Health checks
- Upload validation
- CI tests
- Frontend build checks
- Admin settings
- AWS deployment

Remaining production-readiness work:

- More backend permission coverage
- QC approval workflow
- S3 or external file storage
- Formal backup/restore documentation
- System status dashboard
- Monitoring and alerting
- Secure production settings review
- More complete user management
- More robust reporting/export workflows

---

## 📌 Project Goals

OpenLIMS aims to be:

- Lightweight
- Deployable
- Configurable
- Open-source friendly
- Production-shaped
- Useful for real lab workflows
- Easy to run locally or on low-cost cloud infrastructure


---

## 👨‍💻 Author

Eduardo L

---

## 📄 License

Apache 2.0
