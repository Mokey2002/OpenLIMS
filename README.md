# OpenLIMS

OpenLIMS is a lightweight, open-source Laboratory Information Management System (LIMS) designed to be easy to deploy, configure, and operate in labs worldwide.

The goal is to provide a **production-shaped but simple** LIMS that works out of the box with minimal IT overhead.

---

## Features (MVP)

- Sample tracking
- Container and location management
- Audit trail for all actions
- Role-based access control
- REST API
- One-command deployment with Docker Compose

---

## Architecture

- **Backend:** Django + Django REST Framework
- **Database:** PostgreSQL
- **Deployment:** Docker Compose (single-node)
- **Optional:** Redis for background tasks

---

## Quickstart

### Prerequisites
- Docker
- Docker Compose

### Run locally

```bash
git clone https://github.com/Mokey2002/OpenLIMS.git
cd OpenLIMS
cp deploy/.env.example deploy/.env
docker compose up --build

