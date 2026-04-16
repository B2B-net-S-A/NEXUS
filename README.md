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

- 👥 **Candidate Database** — full profile, structured skills with `must`/`nice` + verification, CV upload, semantic search, preferences (remote modes, rate range, excluded clients), champion/verifier flags
- 📋 **Job Management** — pipeline, portal syndication, **hybrid AI matching with explainable score breakdown**, AI-generated must/nice criteria (Ollama)
- 🎯 **Pipeline Templates** — custom stages per job/client, drag-drop reorder, rejection reasons, per-stage scorecards with rating/text/checkbox/select questions, SLA max_days per stage
- 🏢 **Client CRM** — companies, contacts, NDA tracking
- 🔄 **Recruitment Pipeline** — Kanban board, stage history, audit trail, multi-select bulk move, **per-candidate multi-pipeline view**
- 🔬 **Hybrid Recommendations** — semantic (Qdrant) + skills overlap + salary fit + location + availability, with blacklist/conflict/excluded-client penalties. Both directions: `jobs → candidates` and `candidate → jobs`.
- 💰 **Rate History** — per-candidate compensation log (B2B/UoP/Zlecenie) with client/project context
- ⛔ **Conflicts** — client↔candidate guards (blacklist, current employment, NDA, competitor)
- 📝 **Notes** — call/meeting/email notes per candidate or job
- 📄 **Contracts** — B2B/UoP/Zlecenie, auto margin calculation, expiry alerts
- 📊 **Dashboard + Analytics** — KPIs, recent activity, pipeline funnel, time-to-hire per recruiter, SLA alerts
- 🔍 **Search** — full-text (PostgreSQL) + semantic (Qdrant/Voyage) + **saved searches** (per-user, shareable)
- 📜 **Match History** — per (candidate, job) timeline of scoring snapshots for retrospective analysis
- 🔒 **Roles** — Admin, Recruiter, Manager, Client
- 🛠️ **Diagnostics** — Voyage/Qdrant health + collection init from UI

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
| POST | `/api/candidates` | Create candidate (with preferences/champion/verifier) |
| POST | `/api/candidates/check-duplicates` | Pre-create dedup warning |
| POST | `/api/candidates/{id}/cv` | Upload CV |
| GET | `/api/candidates/{id}/pipelines` | All pipelines for a candidate |
| GET | `/api/candidates/{id}/rate-history` | Rate history log |
| GET | `/api/candidates/{id}/conflicts` | Active client conflicts |
| GET | `/api/candidates/{id}/recommendations` | Suggested jobs (hybrid) |
| POST | `/api/candidates/{id}/assign-to-job/{job_id}` | Add to recruitment pipeline |
| GET | `/api/jobs` | List jobs |
| POST | `/api/jobs/{id}/publish` | Publish to portals |
| GET | `/api/jobs/{id}/recommendations` | **Hybrid recommendations** with breakdown |
| POST | `/api/jobs/{id}/refresh-criteria` | AI-generate must/nice skills (Ollama) |
| POST | `/api/jobs/{id}/recompute-scores` | Batch rescore |
| POST | `/api/pipeline/move` | Move stage (legacy enum or stage_def_id) |
| POST | `/api/pipeline/bulk-move` | Multi-candidate move |
| GET | `/api/pipeline/kanban/{job_id}` | Kanban view |
| GET | `/api/pipeline/overview-sla` | SLA alerts per stage |
| GET | `/api/pipeline-stages/{id}/scorecard` | Scorecard schema |
| PATCH | `/api/pipeline/{stage_id}/scorecard` | Submit scorecard answers |
| GET | `/api/pipeline-templates` | List templates |
| POST | `/api/pipeline-templates/{id}/clone` | Clone template |
| POST | `/api/pipeline-templates/assign-to-job/{job_id}` | Assign template |
| GET | `/api/contracts/expiring` | Expiring contracts alert |
| GET | `/api/dashboard/stats` | KPI stats |
| GET | `/api/reports/funnel` | Pipeline funnel report |
| GET | `/api/reports/time-to-hire` | Time-to-hire per recruiter |
| GET | `/api/search/?q=` | Full-text search |
| GET | `/api/search/semantic?q=` | Semantic search |
| GET/POST | `/api/saved-searches` | Per-user named filter presets |
| GET/POST | `/api/match-history` | Per (candidate,job) scoring timeline |
| GET | `/api/embed-diagnostics` | Voyage/Qdrant health |
| POST | `/api/embed-init` | Create/verify Qdrant collections |

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

Completed:
- [x] Phase 1 — Structured skills (must/nice), pipeline templates, rejection reasons, duplicate detection
- [x] Phase 2 — Hybrid recommendations with explainable ScoreBreakdown (both directions)
- [x] Phase 3 — Stage-specific scorecards, SLA alerts, multi-pipeline candidate view, funnel/time-to-hire reports
- [x] Phase 4 — Saved searches, match history, AI-generated criteria (Ollama), bulk kanban ops
- [x] Phase 5 — Embedding diagnostics UI, rate history CRUD, client-candidate conflicts CRUD

Next:
- [ ] CV auto-parsing (Ollama LLM)
- [ ] Pracuj.pl / LinkedIn portal integration via n8n
- [ ] Email automation (follow-ups, rejections)
- [ ] Traffit ATS import (40k CVs migration)
- [ ] Multi-language CV processing
- [ ] Mobile-friendly kanban

See [docs/pipeline-templates.md](docs/pipeline-templates.md) for custom pipeline setup guide.

---

*Built for B2B.net S.A. — Talent Solutions division, project codename: Nexus*
