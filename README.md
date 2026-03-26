# OpenLIMS

OpenLIMS is a lightweight, production-style Laboratory Information Management System (LIMS) designed to manage samples, workflows, and laboratory results with minimal setup.

It is built to demonstrate real-world backend architecture, workflow orchestration, and auditability in a lab environment.

---

## 🚀 Key Features

### 🧪 Sample Management
- Create and track samples
- Assign containers and metadata
- Search and filter samples by ID and status

### 🔄 Workflow Engine
- Enforced state transitions:
- Received-IN_PROGRESS-QC-REPORTED-ARCHIVED
- Invalid transitions are blocked at the API level
- UI-driven workflow actions

### 📜 Audit Trail (Events)
- All actions are logged
- Includes:
- timestamp
- payload
- actor (user)
- Per-sample timeline view

### 🧩 Custom Fields (Dynamic Schema)
- Define fields without code changes
- Supports validation rules
- Attached to entities (e.g. Sample)

### 🧬 Work Items & Results
- Model lab processes (e.g. DNA Extraction, QC)
- Attach structured results:
- numeric
- string
- boolean
- Results linked to samples via work items

### 📊 Dashboard
- Sample counts by status
- Charts (React + Chart.js)
- Recent activity feed

### 🔐 Authentication & Authorization
- JWT-based authentication
- Role-based access:
- admin
- tech
- viewer

### 🐳 Deployment
- One-command setup with Docker Compose
- Production-shaped architecture

---

## 🏗 Architecture

- **Backend**: Django + Django REST Framework  
- **Frontend**: React (Vite) + Bootstrap  
- **Database**: PostgreSQL  
- **Auth**: JWT (SimpleJWT)  
- **Containerization**: Docker + Docker Compose  

### Services

- `api` — Django backend
- `db` — PostgreSQL database

All services communicate via REST APIs.

---

## ⚡ Quickstart

### Prerequisites
- Docker
- Docker Compose

### Run locally

```bash
git clone https://github.com/Mokey2002/OpenLIMS.git
cd OpenLIMS
cp deploy/.env.example deploy/.env
docker compose up --build
