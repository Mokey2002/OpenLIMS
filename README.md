# 🧪 OpenLIMS

<p align="center">
  <strong>Open-source, self-hosted Laboratory Information Management System for practical lab workflows.</strong>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-v0.28.1-blue">
  <img alt="License" src="https://img.shields.io/badge/license-Apache%202.0-green">
  <img alt="Backend" src="https://img.shields.io/badge/backend-Django%20REST%20Framework-darkgreen">
  <img alt="Frontend" src="https://img.shields.io/badge/frontend-React%20%2B%20Vite-61DAFB">
  <img alt="Database" src="https://img.shields.io/badge/database-PostgreSQL-336791">
  <img alt="Assistant" src="https://img.shields.io/badge/assistant-OpenLIMS%20%7C%20OpenAI%20%7C%20Ollama-purple">
</p>

---

## Overview

**OpenLIMS** is an open-source, self-hosted Laboratory Information Management System for research labs, small biotech teams, core facilities, and developers who need more structure than spreadsheets without the cost or complexity of a traditional enterprise LIMS.

It supports sample tracking, projects, configurable workflows, collaborative notebooks, inventory custody, internal assay requests, instrument imports, sequence analysis, BLAST, mass spectrometry review, data migration, audit trails, reporting, role-based access control, and an assistant with optional OpenAI or local Ollama support.

> **Status:** OpenLIMS is a production-style prototype. It is not yet a fully validated clinical, diagnostic, or regulated production LIMS.

**Current release:** `v0.28.1 — Product Hardening and My Work`

---

## ✨ What’s new in v0.28.1

### Unified My Work dashboard

The signed-in home page is now a single **My Work** workspace that brings together:

- Assigned work
- Workflow requests
- Notebook experiments when enabled
- QC items needing attention
- Inventory and operational alerts
- Unread notifications
- Overdue work

This reduces the need to jump between many separate screens to understand what needs attention.

### Simpler workflow navigation

The main application navigation is organized around the lab workflow:

```text
Plan → Receive → Execute → Review → Report
```

Navigation is role-aware, supports favorites, and keeps optional modules such as Notebook and Registry hidden when their feature flags are disabled.

### Secure browser authentication

Browser authentication was hardened substantially:

- Access and refresh JWTs are stored in **HttpOnly cookies**, not `localStorage`
- CSRF protection is enforced for cookie-authenticated write requests
- Refresh-token rotation is enabled
- Rotated and logged-out refresh tokens are blacklisted
- Logout invalidates the browser session
- Content Security Policy and additional security headers are applied
- Browser WebSockets use the authenticated session cookie instead of exposing a token in the URL
- Bearer-token authentication remains available for scripts and non-browser API clients

### Versioned browser API traffic

The frontend now routes normal application API traffic through `/api/v1/` while preserving compatibility routes where needed. Shared frontend request helpers provide consistent session credentials, CSRF handling, refresh behavior, downloads, form uploads, and retry behavior.

### Backend-enforced feature flags

Notebook and Registry feature flags no longer only hide menu entries. When disabled, the corresponding backend API routes are blocked as well.

### Production deployment support

v0.28.1 adds a production Compose configuration with:

- PostgreSQL and Redis kept internal by default
- Persistent PostgreSQL, Redis, media, and static volumes
- Daphne ASGI application server
- Celery worker
- Production frontend image served by Nginx
- Health checks and service dependencies
- WebSocket proxying
- Optional Ollama profile
- Configurable public HTTP port

### Frontend end-to-end testing

Playwright browser tests now exercise critical product flows including:

- Login
- HttpOnly browser sessions
- No JWT persistence in browser storage
- My Work loading
- Versioned API usage
- Main workflow navigation
- Logout and session invalidation

GitHub Actions now validates the backend suite, Django checks, migration consistency, frontend production build, production Compose configuration, and Playwright E2E flows.

---

## Previous release: v0.28.0

v0.28.0 introduced Inventory v2 and Workflow Requests v1, including:

- Site-to-well inventory hierarchies and plate maps
- Generic barcodes and scan-based inventory operations
- Immutable quantity ledger and provenance
- Reagent, vendor, lot, storage, safety, SDS, and COA metadata
- Expiration, reorder, reservation, and cycle-count workflows
- Configurable internal assay request forms
- Triage, approval, rejection, cancellation, due dates, and SLAs
- Dependency-aware pipeline assignment
- Batch and plate run groups
- Automatic material reservations
- Requester-visible execution, QC, results, attachments, and approved reports

---

## 🧭 Core product areas

| Area | Capabilities |
|---|---|
| **My Work** | Unified assigned-work, request, experiment, QC, alert, notification, and overdue-work dashboard |
| **Samples** | Lifecycle tracking, aliquots, parent/child lineage, custody, statuses, attachments, custom fields, reason-for-change logging |
| **Projects** | Project workspaces, membership, scoped visibility, cross-project sample linking |
| **Pipelines** | Dependency graphs, parallel/conditional steps, optional work, controlled retries, defaults, QC gates |
| **Analyses & procedures** | Configurable analysis types, required result schemas, versioned procedures, SOP links |
| **Notebook** | Collaborative notebooks, block experiments, immutable revisions, comments, assignments, review/sign-off, locking, cloning, PDF export |
| **Inventory** | Site-to-well hierarchy, barcodes, plate maps, reagent/lot metadata, immutable scan ledger, reservations, alerts, cycle counting |
| **Workflow Requests** | Configurable assay forms, triage/approval, SLAs, pipeline assignment, resource reservation, execution status, reports |
| **Imports** | Instrument CSV imports, flexible header detection, direct instrument/API ingestion |
| **Migration** | Legacy migration profiles, reusable field mappings, preview/dry-run, reconciliation, rollback support |
| **Sequences** | FASTA import, sequence workspaces, metadata, features |
| **Registry** | Configurable biological entities, immutable versions, aliases, relationships, duplicate detection, review/registration |
| **Molecular Biology** | DNA/RNA/protein validation, revision tools, digests, construct assembly, feature libraries, FASTA/GenBank interchange |
| **Alignments** | Clustal Omega alignment jobs and downloadable output |
| **BLAST** | Local BLAST database building and blastn/blastp search |
| **Mass Spec** | mzML/mzXML/mzData and OpenMS-compatible review using pyOpenMS |
| **Audit** | Audit events, custody transfers, reason-for-change tracking, exports |
| **Reports** | Project, sample, QC, import, audit, comparison, and investigation reports |
| **Assistant** | OpenLIMS Rules with optional OpenAI or Ollama, clarification, context, investigations, and confirmed actions |
| **Localization** | Director-controlled English or Spanish interface |

---

## 🔐 Security and permissions

OpenLIMS uses role-based permissions and project-scoped access controls.

| Role | Purpose |
|---|---|
| **Admin / Director** | Full system access |
| **Tech** | Lab workflow access for assigned projects |
| **Viewer** | Read-only access |

Browser sessions use HttpOnly JWT cookies with CSRF protection, refresh rotation, and logout invalidation. Bearer JWT authentication remains supported for compatible scripts and API clients.

Feature flags are enforced in both navigation and backend API access for guarded modules.

> Production operators should configure a strong Django secret key, allowed hosts, trusted CSRF origins, HTTPS at the edge, secure cookies, backups, and monitoring appropriate to their environment.

---

## 🏗 Architecture

| Layer | Technology |
|---|---|
| **Frontend** | React + Vite |
| **Production frontend** | Nginx |
| **Backend API** | Django REST Framework |
| **ASGI** | Daphne |
| **Database** | PostgreSQL |
| **Background jobs** | Celery |
| **Broker / cache** | Redis |
| **Real-time updates** | Django Channels + WebSockets |
| **Alignments** | Clustal Omega |
| **BLAST** | NCBI BLAST+ |
| **Mass Spec** | pyOpenMS |
| **Assistant** | OpenLIMS Rules, optional OpenAI, optional Ollama |
| **Deployment** | Docker Compose |

```text
Browser
  ↓
Nginx / upstream TLS proxy
  ↓
React frontend + /api + /ws proxying
  ↓
Django REST Framework / Daphne
  ↓
PostgreSQL

Redis
  ↓
Celery workers
  ↓
Imports / Migrations / Alignments / BLAST / Mass Spec
```

---

## 💻 Local development

### 1. Clone

```bash
git clone https://github.com/Mokey2002/OpenLIMS.git
cd OpenLIMS
```

### 2. Create the local environment

```bash
cp deploy/.env.example deploy/.env
```

For browser development, ensure the frontend origins are trusted for CSRF, for example:

```env
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

### 3. Start the stack

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

`seed_demo` is idempotent. Newly created demo identities intentionally receive unusable passwords; it does not publish or install shared demo credentials. Sign in with an existing OpenLIMS administrator account to explore the seeded data.

### 6. Open the app

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| API | http://localhost:8000 |
| Admin | http://localhost:8000/admin |
| Health | http://localhost:8000/api/health/ |

---

## 🚀 Production deployment

A production Compose file is included at `deploy/docker-compose.prod.yml`.

Start from the production environment template:

```bash
cp deploy/.env.prod.example deploy/.env
```

Before starting the stack, replace placeholder secrets and configure the public hostname and trusted CSRF origin for your deployment.

Then build and start:

```bash
docker compose -p openlims -f deploy/docker-compose.prod.yml up -d --build
```

The frontend is exposed on port `8080` by default and can be changed with `OPENLIMS_HTTP_PORT`.

For an Internet-facing deployment, terminate HTTPS at a trusted reverse proxy or load balancer and configure the Django proxy/security settings consistently with that topology.

### Optional local Ollama

The production Compose file includes an optional `llm` profile:

```bash
docker compose -p openlims -f deploy/docker-compose.prod.yml --profile llm up -d
```

### Database backup

```bash
docker compose -p openlims -f deploy/docker-compose.prod.yml exec db pg_dump -U openlims openlims > openlims_backup.sql
```

Restore:

```bash
cat openlims_backup.sql | docker compose -p openlims -f deploy/docker-compose.prod.yml exec -T db psql -U openlims openlims
```

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

Verify no uncommitted Django migrations are required:

```bash
docker compose -p openlims -f deploy/docker-compose.yml exec api python manage.py makemigrations --check --dry-run
```

Build the frontend:

```bash
cd frontend
npm ci
npm run build
```

Run Playwright E2E tests after starting a testable OpenLIMS environment:

```bash
cd frontend/e2e
npm ci
npx playwright install chromium
npm test
```

GitHub Actions runs these critical checks automatically for the v0.28.1 pull request.

---

## 🩺 Health check

OpenLIMS includes health endpoints used by local and production containers. Health checks cover core service availability and installed analysis dependencies such as the database, Redis/cache, Clustal Omega, BLAST tools, and pyOpenMS where configured.

---

## 🤖 OpenLIMS Assistant

The assistant uses permission-aware backend tools as its source of truth. OpenLIMS Rules work without an external model, while OpenAI and Ollama can optionally provide constrained language-model assistance.

Supported patterns include searching records, summarizing accessible lab work, reviewing failures, investigations, comparisons, and supported confirmed actions. Actions that require confirmation remain subject to normal permission, preview, audit, and anti-duplication controls.

The UI identifies the active engine, for example:

```text
Using: OpenLIMS Rules
Using: OpenAI · <model>
Using: Ollama · <model>
```

---

## 📌 Current project status

OpenLIMS now includes production-shaped patterns across the application:

- Unified My Work workspace
- Workflow-oriented navigation
- Secure browser cookie sessions
- CSRF protection and security headers
- Versioned `/api/v1/` browser traffic
- Server-enforced feature flags
- Role-based and project-scoped access control
- PostgreSQL, Redis, Celery, Daphne, and WebSockets
- Production frontend container and Compose stack
- Sample lineage and custody
- Inventory transaction ledger and cycle counts
- Workflow requests and resource reservations
- Collaborative notebooks and immutable revisions
- Registry and molecular-biology tooling
- Instrument imports and migration toolkit
- Sequence, alignment, BLAST, and mass-spectrometry workflows
- Audit events and reason-for-change logging
- Reports and global search
- OpenLIMS Assistant with optional OpenAI/Ollama
- English/Spanish interface
- Backend, production-build, Compose, and Playwright CI coverage

Remaining production-readiness work includes areas such as:

- Formal record-retention and archive policies across all regulated record types
- SSO and optional MFA
- External/S3-compatible file storage
- More formal backup/restore automation
- Monitoring and alerting
- Broader regression and load testing
- Validation-readiness documentation
- Formal regulated-environment validation packages

---

## 🗺 Roadmap

Planned and future improvements include:

- Formal retention/archival controls instead of destructive deletion for laboratory records
- SSO and optional MFA
- External object storage
- Monitoring and alerting
- Additional QC and approval workflows
- More advanced migration connectors
- Broader browser regression coverage
- Validation-readiness documentation
- Continued workflow, reporting, and assistant improvements

See [`docs/product_hardening_v0281.md`](docs/product_hardening_v0281.md) for additional v0.28.1 implementation notes.

---

## 🎯 Project goals

OpenLIMS aims to be:

- Lightweight
- Self-hosted
- Configurable
- Open source and extensible
- Practical for real laboratory workflows
- Easy to run locally or on low-cost infrastructure
- Useful for research groups, core facilities, and biotech teams
- A strong foundation for laboratory workflow automation

---

## 👤 Author

**Eduardo L**

LinkedIn: https://www.linkedin.com/in/edlemus/

---

## 📄 License

Copyright © 2026 Eduardo Lemus.

OpenLIMS is open-source software licensed under the [Apache License 2.0](LICENSE). You may use, modify, and distribute the source code in accordance with the license terms.

Third-party dependencies and bundled components remain subject to their own licenses. See [`docs/licensing_history.md`](docs/licensing_history.md) for the project's licensing history.
