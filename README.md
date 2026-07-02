# OpenLIMS

OpenLIMS is an open-source, self-hosted Laboratory Information Management System (LIMS) built to support practical lab workflows such as sample tracking, project organization, inventory storage, instrument data ingestion, sequence analysis, local BLAST search, mass spectrometry review, legacy data migration, audit trails, reporting, and role-based access control.

The project is designed as a lightweight, configurable, production-style foundation for research labs, small biotech teams, core facilities, and developer teams that need more structure than spreadsheets but do not want the cost or complexity of a traditional enterprise LIMS.

> OpenLIMS is currently a production-style prototype. It is not yet a fully validated clinical, diagnostic, or regulated production LIMS.

## Live Demo

OpenLIMS is currently deployed here:

```text
http://16.146.193.92
```

## Demo Users

| User | Password | Role |
|---|---|---|
| director | Director123! | Admin / director access |
| peter | peter123 | Lab tech access |
| maria | maria123 | Lab tech access |
| michael | michael123 | Lab tech access |
| viewer | viewer123 | Read-only access |

## What OpenLIMS Does

OpenLIMS brings together several common lab workflow needs in one self-hosted application:

- Sample lifecycle tracking
- Project-based organization
- Project-scoped sample visibility
- Cross-project sample linking
- Inventory locations and containers
- Sample attachments
- Custom fields
- Instrument CSV imports
- Flexible CSV header detection
- Direct instrument/API ingestion
- Work items and structured results
- FASTA import workflows
- Sequence workspaces
- Clustal Omega alignments
- Local BLAST database building and search
- Mass spectrometry file processing and comparison
- Data migration toolkit for legacy lab database exports
- Migration profiles and reusable field mappings
- CSV migration preview / dry-run
- Confirmed migration import
- External sample IDs and aliases
- Audit trails and reason-for-change logging
- Notifications
- Reports and CSV exports
- Global search
- System health checks
- Real-time background job updates

## Core Concepts

### Samples

Samples are the central records in OpenLIMS. A sample can be assigned to a project, placed in a container, linked to results, connected to sequence records, used in BLAST or alignment workflows, associated with mass spectrometry runs, and connected to external IDs from legacy systems.

Supported sample statuses include:

```text
RECEIVED
IN_PROGRESS
QC
REPORTED
ARCHIVED
```

OpenLIMS also supports controlled status changes with a required reason for change. This helps create a stronger chain-of-custody and audit trail.

### Projects

Projects act as shared workspaces for lab teams. They can contain samples, sequence workspaces, imports, BLAST jobs, alignments, mass spec runs, notes, migration jobs, and project activity.

Project membership controls what non-admin users can see and modify.

### Cross-Project Sample Linking

A sample has one primary project, but it can also be linked to additional projects.

This supports cases where a sample belongs to one study or team but needs to be visible to another project without transferring ownership.

Example:

```text
S-ALPHA-001
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

### Instrument Imports

OpenLIMS supports CSV-based instrument imports and direct API ingestion.

Instrument profiles define:

- Instrument code
- Instrument name
- Delimiter
- Sample ID column
- Column mappings
- Value types
- Numeric limits
- Allowed values
- Header row behavior
- Auto-detection of true CSV headers

This makes it possible to import data from common lab instruments and convert rows into samples, work items, and structured results.

### Flexible CSV Imports

Some instrument exports include metadata rows before the real CSV header. OpenLIMS supports flexible CSV parsing so the system can scan for the sample ID column and detect the actual header row.

Example:

```csv
Instrument,Example Analyzer
Run ID,RUN-001
Operator,Peter
sample_id,result,operator,qc_status
S-ALPHA-001,pass,Peter,PASS
```

OpenLIMS can skip the metadata rows and process the real table.

### Data Migration Toolkit

OpenLIMS includes a data migration toolkit for bringing legacy lab database exports into OpenLIMS in a safer, reviewable way.

Instead of directly copying an old database into OpenLIMS, users can export legacy data as CSV, define a reusable migration profile, map old columns to OpenLIMS fields, preview the migration, and then confirm the import.

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
- Audit events for completed migrations

Example workflow:

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

This is useful for labs moving away from custom databases or spreadsheets because OpenLIMS can preserve old identifiers while mapping the data into its project, sample, result, and audit model.

### External Sample IDs and Aliases

OpenLIMS can preserve legacy identifiers from older databases or spreadsheets.

Example:

```text
Sample: S-UW-001
Source System: UW Legacy DB
Label: legacy_specimen_id
External ID: SP-00921
```

This lets labs keep searching and tracing data using IDs from their previous systems while still organizing the data inside OpenLIMS.

### Sequence Workspaces

OpenLIMS includes sequence workspace support for DNA, RNA, and protein records.

Users can:

- Create sequence records
- Link sequences to samples and projects
- Store sequence metadata
- Add sequence features
- Import FASTA files
- Use sequences in alignment and BLAST workflows

Example workflow:

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

### Audit Trail

OpenLIMS records important activity as audit events.

Examples include:

- Sample created
- Sample status changed
- Sample linked to project
- Sample unlinked from project
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

For controlled sample status changes, OpenLIMS records:

- Actor
- Before state
- After state
- Changed fields
- Reason for change
- Timestamp

### Reports

OpenLIMS includes operational reports and CSV exports for:

- Project summaries
- Sample inventory
- QC review
- Import summaries
- Alignment summaries
- BLAST summaries
- Audit activity

### Real-Time Job Updates

Background jobs run through Celery and Redis. OpenLIMS uses Django Channels and WebSockets to update the frontend when jobs change status.

Supported live-update workflows include:

- CSV imports
- Alignment jobs
- BLAST database builds
- BLAST searches
- Mass spec processing

## Permissions

OpenLIMS uses JWT authentication and role-based permissions.

| Role | Purpose |
|---|---|
| Admin / Director | Full system access |
| Tech | Lab workflow access for assigned projects |
| Viewer | Read-only access |

### Sample Access Rules

| Role | Sample Visibility | Modify Samples |
|---|---|---|
| Admin / Director | All samples, including unassigned samples | Yes |
| Tech | Samples in assigned projects, linked project samples, and unassigned samples they created | Only samples they have modification rights for |
| Viewer | Samples in assigned or linked projects | No |

Linked-project access allows a user to see a sample, but it does not automatically grant edit or import permissions.

## Architecture

OpenLIMS is built with:

| Layer | Technology |
|---|---|
| Frontend | React + Vite |
| Backend API | Django REST Framework |
| Database | PostgreSQL |
| Background Jobs | Celery |
| Broker / Cache | Redis |
| Real-Time Updates | Django Channels + Daphne |
| Alignments | Clustal Omega |
| BLAST | NCBI BLAST+ |
| Mass Spec | pyOpenMS |
| Reverse Proxy | Caddy |
| Deployment | Docker Compose |

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
```

## Main Django Apps

| App | Responsibility |
|---|---|
| samples | Sample lifecycle, access control, attachments, transitions |
| projects | Projects, membership, project posts |
| inventory | Locations and containers |
| imports | Instrument profiles, CSV imports, direct instrument ingestion |
| migration_toolkit | Legacy CSV migration profiles, field mappings, dry-run previews, imports, and external IDs |
| results | Work items and structured results |
| events | Audit trail and audit export |
| notifications | User notifications |
| custom_fields | Configurable fields |
| sequences | Sequence records and features |
| alignments | Clustal Omega alignment jobs |
| blast | BLAST databases, jobs, and hits |
| mass_spec | Mass spec uploads, processing, summaries, and comparison |
| settings_app | Admin settings |
| core | Users, roles, permissions, search, shared utilities |

## Local Development

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

```text
Frontend: http://localhost:5173
API:      http://localhost:8000
Admin:    http://localhost:8000/admin
Health:   http://localhost:8000/api/health/
```

## Running Tests

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

## Health Check

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

## Deployment Notes

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

## Database Backup

Create a backup:

```bash
docker compose -p openlims -f deploy/docker-compose.prod.yml exec db pg_dump -U openlims openlims > openlims_backup.sql
```

Restore a backup:

```bash
cat openlims_backup.sql | docker compose -p openlims -f deploy/docker-compose.prod.yml exec -T db psql -U openlims openlims
```

## Current Project Status

OpenLIMS is a production-style open-source LIMS prototype with many production-shaped patterns already in place:

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

## Roadmap

Planned and future improvements include:

- More advanced migration support for multi-file exports and direct database imports
- Expanded relationship tracking for derived samples
- More advanced QC approval workflows
- Better dashboards for lab operations
- External file storage support
- Monitoring and alerting
- Validation-readiness documentation

## Project Goals

OpenLIMS aims to be:

- Lightweight
- Self-hosted
- Configurable
- Open-source friendly
- Practical for real lab workflows
- Easy to run locally or on low-cost cloud infrastructure
- Useful for small labs, research groups, and biotech teams
- A strong foundation for lab workflow automation

## Author

Eduardo L

LinkedIn: https://www.linkedin.com/in/edlemus/

## License

Apache 2.0
