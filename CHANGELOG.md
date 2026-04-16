# Nexus ATS — Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com) and semver-like `MAJOR.MINOR.PATCH`.

## [0.4.0] — 2026-04-16 — Phase 1 complete

Full Phase 1 of the matching-engine and pipeline-template roadmap. Backward-compatible
with any existing records (legacy `candidate_stages.stage` enum stays populated).

### Added — Data model foundations (Sprint 1, PR #1)

- **Candidate** (`candidates`):
  - `years_it_experience` — dedicated column for structured IT experience
  - `preferences` JSONB — remote_modes, rate_min/max/currency, industries, excluded_clients, contract_types
  - `champion` boolean flag for top performers
  - `verifier_id` (FK users) + `verified_tech` JSONB for screening validation
- **Job** (`jobs`):
  - `must_skills` / `nice_skills` JSONB — structured criteria for the Phase 2 matching engine
  - `seniority` enum (junior / mid / senior / lead / architect) + `work_mode` enum (fulltime / parttime / contract)
  - `headcount` — number of open slots
  - `reference_number` (unique where not null) — B2B ref number
  - `industry`, `subcategory` — hierarchical taxonomy
  - `custom_fields` JSONB — reserved for Phase 4 custom-fields engine
  - `embedding_id`, `criteria_generated_at` — reserved for Phase 2 recommendations
- **RateHistory** (new table `candidate_rate_history`) — per-engagement rates with contract type enum (b2b/uop/zlecenie)
- **CandidateConflict** (new table `candidate_conflicts`) — hard-filter blacklist client↔candidate with partial unique index on active=true
- **Skills JSONB validator** — `[{name, level, years, category}]`, legacy string lists auto-normalized
- **Duplicate detection** — `dedup_service.find_candidate_duplicates` + `POST /api/candidates/check-duplicates` (non-blocking warning)
- **CV upload auto-embed** — `POST /candidates/{id}/cv` now triggers `embed_candidate` (was disconnected)
- **Enriched candidate embed text** — seniority hint from `years_it_experience`, `verified_tech`, `preferences.industries`

### Added — Pipeline templates (Sprint 2, PR #2)

- **PipelineTemplate** / **PipelineStageDef** / **RejectionReason** — elastic replacement for the hardcoded `PipelineStage` enum
- **Migration 0006** seeds "Default B2B" template mirroring the 12 legacy stages + 10 structured rejection reasons; backfills every job and candidate_stages row
- **`/api/pipeline-templates/*`** — 9 new endpoints (list/detail/CRUD/clone/reorder/assign-to-job)
- **`/api/pipeline/*`** refactor — `/stages?job_id=`, `/move` accepts `stage_def_id` + `rejection_reason_id`, `/kanban/{id}` driven by template
- **Pipeline builder UI** — `/settings/pipeline-templates` with drag-drop reorder, create/clone/archive, stage + rejection reason management
- **KanbanBoard** — fully dynamic columns; no more hardcoded 12-stage maps
- **RejectionReasonModal** — appears on terminal drops (Odrzucony / Wycofany)
- **Sidebar** — new "Procesy rekrutacyjne" link under SYSTEM

### Added — UI polish (Sprint 3, PR #3)

- **Duplicate warning banner** in `AddCandidateModal` — "Sprawdź duplikaty" button → yellow banner lists up to 5 matching candidates with match score and link to their profile
- **CHANGELOG.md** — this file

### Fixed — CI (Sprints 1-2)

- `secret-scan`: granted `contents:read` + `pull-requests:read` so gitleaks can list PR commits
- `backend-lint-test`: use `alembic -c alembic/alembic.ini upgrade head` (ini lives inside `alembic/`)
- `frontend-lint-build`: `npm ci --legacy-peer-deps` (@hello-pangea/dnd declares peer react@^18, project uses react@19)
- `npm run lint` temporarily skipped — `next lint` prompts interactively without a committed eslint config; restored in Phase 3
- Base re-export in `app/models/base.py` — restored `from app.core.database import Base` after a ruff pass removed it (alembic 0001_initial needs it)
- `ruff --fix --unsafe-fixes` ran over the legacy backend — 58 pre-existing errors → 0

### Backward-compat notes

- `candidate_stages.stage` (enum) **stays populated** alongside the new `stage_def_id` FK. Drop planned for Phase 3.
- All migrations are idempotent (`IF NOT EXISTS`) so they coexist safely with the `Base.metadata.create_all(checkfirst=True)` in `0001_initial`.
- Out of scope (documented): GDPR module, CRM sales pipeline (removed in `51362ce`), Pracuj.pl / JJIT scrapers (n8n), public candidate tracker (Phase 4).

### Next — Phase 2

Hybrid recommendations engine (`scoring_service.py`), job embedding (new `nexus_jobs` Qdrant collection), `/api/candidates/{id}/recommendations` reverse endpoint, AI-generated criteria (`Odśwież kryteria` + `Przelicz scoring`), explainable score breakdown tooltip. Target: ~5-8 dev days.
