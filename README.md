# 🧪 OpenLIMS

OpenLIMS is a lightweight, modular, production-inspired Laboratory Information Management System (LIMS) built to support real lab workflows such as sample tracking, project organization, inventory storage, instrument data ingestion, audit trails, notifications, and result analysis.

---

## 🚀 Core Features

### Sample Management
- Track samples through lifecycle statuses: RECEIVED, IN_PROGRESS, QC, REPORTED, ARCHIVED
- Assign samples to projects
- Assign samples to containers and storage locations
- Attach files to samples
- View sample work items, results, and audit timeline

### Project Management
- Create projects
- Assign users to projects
- Add project notes and images
- Restrict project visibility based on membership
- Notify users when project updates are posted

### Inventory Management
- Create storage locations
- Create containers
- Link containers to locations
- Assign samples to containers

### Results and Work Items
- Create work items per sample
- Store structured results
- Support numeric, string, and boolean result values
- Group imported results under instrument-generated work items

### Instrument Data Ingestion
OpenLIMS supports two ingestion modes:

1. CSV upload through the UI
2. Direct instrument/API push

Instrument profiles define how incoming data should be interpreted.

Each instrument can define:
- code
- name
- delimiter
- sample ID column
- column mappings
- validation rules
- allowed values
- min/max numeric limits

### Async Import Processing

CSV imports are processed asynchronously using Celery.

This prevents large uploads from blocking the API request.

```text
User uploads CSV
   ↓
Django API creates ImportJob with PENDING status
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

### Audit Trail

OpenLIMS records important actions as events.

Examples:
- sample created
- sample status changed
- results imported
- attachment uploaded
- project post created

Audit events can store before/after state for traceability.

### Notifications

OpenLIMS includes notifications for user-facing activity such as:
- completed imports
- failed imports
- new project posts

### Analysis

The Analyze page supports:
- selecting projects
- selecting samples
- selecting numeric result metrics
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

Async path:
Django API
   ↓
Redis Queue
   ↓
Celery Worker
   ↓
PostgreSQL
```

### Services

| Service | Purpose |
|---|---|
| React | Frontend UI |
| Django REST Framework | API and business logic |
| PostgreSQL | Primary database |
| Redis | Celery message broker |
| Celery Worker | Background import processing |
| Docker Compose | Local orchestration |

---

## 🗂️ Main Django Apps

| App | Responsibility |
|---|---|
| samples | Sample lifecycle, transitions, attachments |
| projects | Project grouping, membership, posts |
| inventory | Locations and containers |
| imports | Instrument profiles, mappings, import jobs |
| results | Work items and structured result values |
| events | Audit trail |
| notifications | User alerts |
| custom_fields | Configurable fields |

---

## 🔁 Import Architecture

### CSV Upload

```text
Frontend Upload Form
   ↓
POST /api/import-jobs/
   ↓
ImportJob created as PENDING
   ↓
process_import_job.delay(job.id)
   ↓
Celery worker reads uploaded CSV
   ↓
Rows processed using instrument mappings
   ↓
Samples/results created
   ↓
ImportJob updated with progress and summary
```

### API Push Model

```text
Instrument / Adapter Script
   ↓
POST /api/import-jobs/instrument-ingest/
   ↓
API key validated
   ↓
Rows validated
   ↓
Samples/results created
   ↓
ImportJob completed
```

Example API request:

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

## 📊 Import Job Progress

Each import job tracks:
- status
- progress_current
- progress_total
- progress_message
- summary
- skipped rows

Statuses:

```text
PENDING → RUNNING → COMPLETED
                  ↘ FAILED
```

Status endpoint:

```text
GET /api/import-jobs/{id}/status/
```

Example response:

```json
{
  "id": 1,
  "status": "RUNNING",
  "progress_current": 25,
  "progress_total": 100,
  "progress_percent": 25,
  "progress_message": "Processed 25 of 100 rows",
  "summary": {}
}
```

---

## 🐳 Local Development

### 1. Clone

```bash
git clone https://github.com/Mokey2002/OpenLIMS.git
cd OpenLIMS
```

### 2. Environment

```bash
cp deploy/.env.example deploy/.env
```

Example environment values:

```env
SECRET_KEY=dev-secret-key
DEBUG=1

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

```bash
docker compose -p openlims -f deploy/docker-compose.yml run --rm api pytest -v
```

Run one test file:

```bash
docker compose -p openlims -f deploy/docker-compose.yml run --rm api pytest imports/tests/test_instrument_ingest.py -v
```

Test coverage includes:
- instrument API ingest
- CSV import workflow
- duplicate run protection
- project permissions
- sample transitions
- notifications
- end-to-end workflows

---

## ✅ CI/CD

GitHub Actions can run:
- Django checks
- migration checks
- tests
- Docker build validation

Example workflow:

```text
Push / PR
   ↓
Build Docker services
   ↓
Run Django checks
   ↓
Run migrations
   ↓
Run pytest
```

---

## 🔐 Authentication and Permissions

OpenLIMS uses:
- JWT authentication for users
- API key authentication for instrument ingestion
- role-based access control

Roles:
- admin
- tech
- viewer

Project access can also be restricted by project membership.

---

## 🧭 Roadmap

### Short Term
- Import job detail page
- Skipped rows CSV download
- Import retry button
- Progress bar UI
- Better sample timeline

### Mid Term
- Async API ingest
- Celery retries
- WebSocket progress updates
- Result edit history
- Data validation UI

### Long Term
- Multi-tenant labs
- Per-instrument API keys
- Kafka ingestion pipeline
- External LIS/LIMS integrations
- Cloud deployment

---

## 📌 Project Goals

OpenLIMS aims to be:
- lightweight
- configurable
- open-source friendly
- easy to deploy
- suitable for many lab types
- production-shaped without enterprise complexity

---

## 👨‍💻 Author

Eduardo L  


---

## 📄 License

Apache 2.0



![Login Screen](./images/login.png)
![Dashboard](./images/dashboard.png)
![Project](./images/projects.png)
![Analyze](./images/analyze.png)
![Samples](./images/samples.png)
