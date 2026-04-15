# Nexus

> **Modern ATS & CRM platform for IT staffing agencies** — built for B2B.net S.A.

Previously developed internally as DynaMinds ATS. Full-stack, async-first, AI-ready.

---

## Stack

| Layer | Tech |
|-------|------|
| **Backend** | FastAPI + SQLAlchemy 2.0 (async) + PostgreSQL |
| **Vector Search** | Qdrant + Voyage AI embeddings |
| **Local AI** | Ollama (llama3.2) |
| **Frontend** | Next.js 15 (App Router) + TypeScript + TailwindCSS |
| **Auth** | JWT (access + refresh tokens), RBAC |
| **Infrastructure** | Docker Compose |

## Features

- 👥 **Candidate Database** — full profile, skills JSONB, CV upload, semantic search
- 📋 **Job Management** — pipeline, portal syndication, AI-matching
- 🏢 **Client CRM** — companies, contacts, NDA tracking
- 🔄 **Recruitment Pipeline** — Kanban board, stage history, audit trail
- 📝 **Notes** — call/meeting/email notes per candidate or job
- 📄 **Contracts** — B2B/UoP/Zlecenie, auto margin calculation, expiry alerts
- 📊 **Dashboard** — KPIs, recent activity, pipeline funnel
- 🔍 **Search** — full-text (PostgreSQL) + semantic (Qdrant/Voyage)
- 🔒 **Roles** — Admin, Recruiter, Manager, Client

---

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.14 (for local dev)
- Node.js 20+ (for local dev)
- Voyage AI API key (for embeddings)

### 1. Clone & configure

```bash
cd Nexus
cp .env.example .env
# Edit .env — add VOYAGE_API_KEY, set SECRET_KEY
```

### 2. Start with Docker

```bash
make build
make up
make migrate
```

- Backend: http://localhost:8000
- Frontend: http://localhost:3000
- API Docs: http://localhost:8000/docs

### 3. Local Development

```bash
# Install dependencies
make install

# Start PostgreSQL + Qdrant via Docker
docker-compose up postgres qdrant -d

# Run migrations
make migrate

# Start backend + frontend
make dev
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/login` | Login → JWT tokens |
| POST | `/api/auth/register` | Register user |
| GET | `/api/auth/me` | Current user |
| GET | `/api/candidates` | List candidates |
| POST | `/api/candidates` | Create candidate |
| POST | `/api/candidates/{id}/cv` | Upload CV |
| GET | `/api/jobs` | List jobs |
| POST | `/api/jobs/{id}/publish` | Publish to portals |
| GET | `/api/jobs/{id}/match-candidates` | AI match (Qdrant) |
| POST | `/api/pipeline/move` | Move stage |
| GET | `/api/pipeline/kanban/{job_id}` | Kanban view |
| GET | `/api/contracts/expiring` | Expiring contracts alert |
| GET | `/api/dashboard/stats` | KPI stats |
| GET | `/api/search/?q=` | Full-text search |
| GET | `/api/search/semantic?q=` | Semantic search |

---

## Project Structure

```
Nexus/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routers
│   │   ├── core/         # Config, DB, security
│   │   ├── models/       # SQLAlchemy models
│   │   └── schemas/      # Pydantic schemas
│   ├── alembic/          # Migrations
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   └── src/
│       ├── app/          # Next.js App Router pages
│       ├── components/   # Shared components
│       ├── lib/          # API client, utils
│       └── store/        # Zustand state
├── docker-compose.yml
├── Makefile
├── .env.example
└── README.md
```

---

## Roles & Permissions

| Role | Access |
|------|--------|
| **Admin** | Full access |
| **Manager** | All operations, no user management |
| **Recruiter** | Candidates, jobs, pipeline, notes |
| **Client** | Read-only: job status, hired candidates |

---

## Semantic Search Setup

1. Set `VOYAGE_API_KEY` in `.env`
2. When uploading a CV, the system parses text and generates an embedding via Voyage AI
3. Embeddings are stored in Qdrant collection `candidates`
4. Use `/api/search/semantic?q=senior python engineer` to query

---

## Roadmap

- [ ] CV auto-parsing (Ollama LLM)
- [ ] Pracuj.pl / LinkedIn portal integration
- [ ] Email automation (follow-ups, rejections)
- [ ] Traffit ATS import (40k CVs migration)
- [ ] Multi-language CV processing
- [ ] Mobile-friendly kanban

---

*Built for B2B.net S.A. — Talent Solutions division, project codename: Nexus*
