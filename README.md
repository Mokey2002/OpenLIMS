# 🧪 OpenLIMS

OpenLIMS is a lightweight, modular, production-inspired **Laboratory Information Management System (LIMS)** designed to support real lab workflows such as sample tracking, project organization, inventory storage, instrument data ingestion, audit trails, notifications, and result analysis.

The goal of OpenLIMS is to provide a configurable, easy-to-deploy LIMS foundation for real laboratory workflows.

---

## 🌐 Live Demo

OpenLIMS is currently deployed here:

```text
http://16.146.193.92
```

---

## 🚀 Features

### Sample Management
- Track samples through lifecycle states:
  - `RECEIVED`
  - `IN_PROGRESS`
  - `QC`
  - `REPORTED`
  - `ARCHIVED`
- Assign samples to projects
- Assign samples to containers and storage locations
- Upload sample attachments
- View sample work items, results, and timeline events

### Project Management
- Create projects
- Assign users to projects
- Restrict project visibility by membership
- Add project notes and images
- Notify project members when updates are posted

### Inventory Management
- Create storage locations
- Create containers
- Link containers to locations
- Assign samples to containers

### Instrument Data Ingestion
OpenLIMS supports two ingestion workflows:

1. **CSV upload through the UI**
2. **Direct instrument/API push**

Instrument profiles define how incoming data should be interpreted.

Each instrument can define:
- instrument name
- instrument code
- delimiter
- sample ID column
- column mappings
- validation rules
- numeric min/max rules
- allowed values

### Async CSV Import Processing
CSV imports are processed asynchronously using **Celery** and **Redis**.

This prevents large imports from blocking API requests.

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

### Import Job Tracking
Each import job tracks:
- status
- source type
- run ID
- progress current
- progress total
- progress message
- rows processed
- samples created
- samples matched
- results created
- skipped rows
- linked samples

Supported statuses:

```text
PENDING → RUNNING → COMPLETED
                  ↘ FAILED
```

### Retry Failed Imports
Failed or completed CSV imports can be retried without uploading the file again.

The original uploaded file is stored with the `ImportJob`, so retry reprocesses the same file.

```text
Original CSV upload
   ↓
ImportJob stores uploaded_file
   ↓
Import fails
   ↓
User clicks Retry Import
   ↓
Celery reprocesses the same stored file
```

### Import-to-Sample Lineage
OpenLIMS links import jobs to the samples they created or matched.

This allows users to answer:

- Which import created this sample?
- Which samples were touched by this run?
- Which instrument run produced these results?

The import summary stores:

```json
{
  "created_sample_ids": [1, 2],
  "matched_sample_ids": [3],
  "touched_sample_ids": [1, 2, 3]
}
```

### Audit Trail / Chain of Custody
OpenLIMS records important actions as audit events.

Examples:
- sample created
- sample status changed
- sample container changed
- attachment uploaded
- results imported
- import retry queued

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

### Notifications
OpenLIMS includes notifications for key activity:
- import completed
- import failed
- project post created
- user-relevant workflow events

### Analysis
The analysis page supports:
- selecting projects
- selecting samples
- choosing numeric result metrics
- graphing values over time
- exporting chart data as CSV

---

## 🧱 Architecture

```text
React Frontend
   ↓
Django REST API
   ↓
PostgreSQL

Async processing:
Django API
   ↓
Redis Queue
   ↓
Celery Worker
   ↓
PostgreSQL
```

### Production Runtime Architecture

```text
Internet
   ↓
Caddy Reverse Proxy
   ↓
React Static Frontend
   ↓
Django API running with Gunicorn
   ↓
PostgreSQL

Celery Worker
   ↓
Redis
   ↓
PostgreSQL
```

### Services

| Service | Purpose |
|---|---|
| React | Frontend UI |
| Django REST Framework | API and business logic |
| PostgreSQL | Primary database |
| Redis | Celery broker/result backend |
| Celery Worker | Background CSV import processing |
| Caddy | Reverse proxy, static file server |
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
| `events` | Audit trail |
| `notifications` | User alerts |
| `custom_fields` | Configurable fields |

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
- shared API key authentication for instrument ingestion
- role-based permissions

Current roles:
- `admin`
- `tech`
- `viewer`

Admin users can:
- manage users
- manage instruments
- manage mappings
- view and manage imports
- access admin-only workflows

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
DEBUG=1
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
docker compose -p openlims -f deploy/docker-compose.yml run --rm api python manage.py migrate
```

### 5. Create superuser

```bash
docker compose -p openlims -f deploy/docker-compose.yml run --rm api python manage.py createsuperuser
```

### 6. Open app

```text
Frontend: http://localhost:5173
API:      http://localhost:8000
Admin:    http://localhost:8000/admin
```

---

## 🧪 Running Tests

Run all tests:

```bash
docker compose -p openlims -f deploy/docker-compose.yml run --rm api pytest -v
```

Run import tests:

```bash
docker compose -p openlims -f deploy/docker-compose.yml run --rm api pytest imports/tests/ -v
```

Test coverage includes:
- instrument API ingest
- CSV import workflow
- duplicate run protection
- import retry validation
- project permissions
- sample transitions
- workflow tests
- notification behavior

---

## ✅ CI/CD

OpenLIMS can run tests through GitHub Actions.

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

## 🧭 Roadmap

### Short Term
- Result edit history
- WebSocket progress updates
- Async API ingest
- Celery retry policies
- Instrument adapter framework
- Advanced search

### Long Term
- Per-instrument API keys
- Multi-tenant labs
- S3 file storage
- External LIMS/LIS integrations
- Kafka-based ingestion
- Workflow engine
- Report generation

---

## 📌 Project Goals

OpenLIMS aims to be:
- lightweight
- deployable
- configurable
- open-source friendly
- production-shaped
- useful for real lab workflows
- easy to run locally or on low-cost cloud infrastructure

---

## 👨‍💻 Author

Eduardo L  


---

## 📄 License

Apache 2.0

