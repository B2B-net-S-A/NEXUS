# Nexus ATS — Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com) and semver-like `MAJOR.MINOR.PATCH`.

## [Unreleased] — Phase 10: Champion Profile + recruiter screening flow

Wewnętrzny szablon "Profil Championa" (wypełniany przez Delivery Leada per rekrutacja) wbudowany w ATS + obligatoryjny flow screeningu kandydata przed rekomendacją do klienta.

### Added — Domain + DB

- **Migracja `0019_champion_profile.py`**:
  - `jobs.champion_profile` JSONB — dokument validowany przez Pydantic `ChampionProfile`.
  - `candidate_stages.screening_answers` JSONB — odpowiedzi rekrutera per stage.
  - Partial index `ix_candidate_stages_has_screening` dla filtrów.
- **Schemas w `app/schemas/champion.py`**: `ChampionProfile`, `ChampionBasics`, `ChampionProjectContext`, `ScreeningQuestion`, `SourcingStrategy`, `ScreeningAnswers`, `ScreeningAnswerItem`.
- **`ScreeningAnswers.match_percent()`** — deterministic 0-100 score: `0` jeśli któryś `deal_breaker_hit`, inaczej `(% odpowiedzianych) × {fit:1.0, uncertain:0.6, miss:0.2}`.

### Added — API

- `GET /api/jobs/{id}/champion-profile` — odczyt (wszystkie role).
- `PUT /api/jobs/{id}/champion-profile` — upsert (Delivery Lead / admin).
- `GET /api/pipeline/stages/{stage_id}/screening` — odpowiedzi + champion profile dla tego stage.
- `POST /api/pipeline/stages/{stage_id}/screening` — recruiter zapisuje odpowiedzi; response ma `match_percent`.

### Added — Frontend

- **`components/ChampionProfileEditor.tsx`** — pełny formularz dla DL: add/remove pytań screeningowych, sourcing checkboxes, read-only mode dla nie-DL.
- **`components/ScreeningModal.tsx`** — modal z pytaniami DL + collapsible ideal answer/deal-breaker, toggle deal_breaker_hit per Q, overall fit (fit/uncertain/miss) + notes.
- **`app/jobs/[id]/page.tsx`** — nowy tab **"Profil Championa"**.
- **`components/KanbanBoard.tsx`**:
  - Auto-open `ScreeningModal` po move do `cv_sent` / `client_interview` / `acceptance` / `negotiation` / `onboarding`.
  - Manualny przycisk **★ Screening** na kartach w external stages.
  - Drag handle zawężony do samej `CandidateCard` — wcześniej blokował klikanie elementów w karcie.
- **`lib/api.ts`** — `championApi` + `screeningApi` + typy.

### Flow

1. Delivery Lead wypełnia Profil Championa (basics + kontekst + pytania + sourcing strategy).
2. Rekruter idzie przez etapy wewnętrzne (new → prep_call → screening → interview).
3. Przy przesunięciu do `cv_sent` `ScreeningModal` otwiera się automatycznie i wymaga odpowiedzi na pytania DL-a.
4. System liczy `match_percent` z uwzględnieniem deal-breakerów; zapisuje `screening_answers` do CandidateStage + Activity log.

### Verified in Chrome

- `PUT /api/jobs/2/champion-profile` z 3 pytaniami zapisuje się OK.
- Tab "Profil Championa" renderuje formularz z pre-filled danymi z backendu.
- `POST /api/pipeline/stages/4/screening` zwraca `match_percent: 100.0` dla idealnej odpowiedzi + brak deal-breakerów.
- ScreeningModal renderuje Q1/Q2 z Championa + pre-fill'uje odpowiedzi rekrutera z wcześniejszego zapisu.

## [Unreleased] — Phase 12: Polish (tests + Playwright + client share)

### Added — Testing

- **6 unit tests dla `_score_champion_fit`** — `_FakeScalarDB` stub mocka `AsyncSession.scalar()` i odpala scenariusze: no screening (neutral 5/10), perfect fit (10/10), deal-breaker (0/10), uncertain 60%, partial answers 50%, invalid payload (graceful).
- **Playwright `auth.setup.ts`** + projects w `playwright.config.ts` — login raz, `storageState` persist, reszta testów idzie od `page.goto("/...")` bez re-login. Wynik: **12/14 pass** (było 6/10).

### Added — Client-facing Champion card share

- **Migracja `0028_champion_share_token.py`** — tabela `champion_card_share_tokens` (token PK, candidate_stage_id FK, created_by, expires_at nullable, revoked bool) + partial index `WHERE revoked IS FALSE`.
- **Model `app/models/champion_share.py` — `ChampionCardShareToken`**.
- **Endpointy w `app/api/pipeline.py`**:
  - `POST /api/pipeline/stages/{id}/share-token?expires_in_days=30` → random 48-char URL-safe token + activity log.
  - `DELETE /api/pipeline/stages/share-token/{token}` → soft-revoke.
- **Endpoint public `app/api/public_share.py`** (bez auth, mount `/api/public`):
  - `GET /api/public/champion-card/{token}` → walidacja `revoked`/`expires_at`, slim response (candidate basics + job + champion_profile + screening_answers).
- **Frontend `/share/champion-card/[token]/page.tsx`** — Server Component, gradient header, sekcje (o projekcie, obowiązki, screening Q+A, notatki), footer z datą ważności.
- **`middleware.ts`** — `PUBLIC_PATHS` += `/share`.
- **`AppShell`** — early-return bez sidebar/onboarding dla `/share/*`.
- **`docker-compose.yml`** — `INTERNAL_API_URL=http://backend:8000` dla frontend SSR.
- **`components/ChampionCard.tsx`** — "Udostępnij" button → API → "Kopiuj link" + external preview.

### Verified in Chrome

- `POST share-token` zwraca `{token, expires_at, share_url_suffix}`.
- `GET /api/public/champion-card/<token>` bez auth → pełny JSON filled card (zweryfikowane z poziomu frontend containera przez `wget`).
- `http://localhost:3001/share/champion-card/<token>` renderuje client-ready kartę (gradient + Q1/Q2 z odpowiedziami + notatki + "Ważne do").

### Migracje head = 0028

## [Unreleased] — Phase 8: RBAC consolidation + login protection

### Changed — Breaking (DB schema)

- **`UserRole` enum** skonsolidowany z poprzedniego dualu `(role, recruiter_role)` do jednej sześciowartościowej hierarchii: `admin`, `delivery_lead`, `tac`, `recruiter`, `sourcer`, `user`.
- **Kolumna `users.recruiter_role` usunięta** wraz z typem enum `recruiterrole`. Mapowanie w migracji `0011_consolidate_user_roles.py`: `manager → delivery_lead`, `client → user`, `recruiter + quality_control → user`, reszta naturalnie.
- **`UserCreate` / `UserUpdate` / `UserResponse` / `AdminUserCreate` / `AdminUserUpdate`** — pole `recruiter_role` usunięte.

### Added — Backend RBAC

- **Nowe guardy w `backend/app/api/deps.py`**: `DeliveryLeadPlus`, `TacPlus`, `RecruiterPlus` (plus zachowany alias `ManagerOrAdmin` = `DeliveryLeadPlus` dla backward compat).
- **Macierz uprawnień przypięta do routerów**: `jobs.py` (create/patch/delete → TacPlus), `contracts.py` (create/patch/delete → TacPlus), `candidates.py` (create/patch/upload-cv/bulk-import → RecruiterPlus, delete → DeliveryLeadPlus), `pipeline.py` (move/bulk-move → RecruiterPlus), `reports.py` (wszystkie → TacPlus), `recommendations.py` (refresh-criteria/recompute → DeliveryLeadPlus).
- **`backend/tests/test_rbac.py`** — parametryzowany test suite dla każdej kombinacji (rola × endpoint): oczekiwane 200/403.

### Added — Frontend login + RBAC

- **`frontend/src/middleware.ts`** — Next.js middleware Edge Runtime dekoduje JWT payload z cookie `nexus_access`, przekierowuje niezalogowanych na `/login?next=<path>` i niewłaściwe role na `/403`.
- **`frontend/src/app/403/page.tsx`** — dedykowana strona błędu RBAC.
- **`frontend/src/components/RequireRole.tsx`** — komponent UI gating z dwoma trybami: exact-match (`roles={...}`) i hierarchiczny (`minRole`).
- **`frontend/src/store/auth.ts`** — rozszerzony `UserRole` do unii 6 wartości, dodane helpery `hasRole`, `hasMinRole`, `ROLE_RANK`, `ROLE_LABELS`. `setAuth`/`logout` synchronizują cookie `nexus_access` z localStorage.
- **`frontend/src/components/Sidebar.tsx`** — wpisy nawigacji filtrowane per rola (`roles?: UserRole[]`); sekcje bez widocznych linków znikają.
- **`frontend/src/app/login/page.tsx`** — obsługa `?next=` (safe allowlist: tylko relatywne ścieżki).
- **`frontend/src/store/auth.test.ts`** — Vitest unit tests dla `hasRole`, `hasMinRole`, niezmienników `ROLE_RANK`.

### Docs

- **`docs/RBAC.md`** — nowy doc: model ról, trzy warstwy autoryzacji (API/route/UI), pełna macierz per-endpoint, instrukcje „jak dodać endpoint / jak zmienić rolę usera".
- **`docs/SUPABASE_ANALYSIS.md`** — analiza za/przeciw migracji na Supabase (wynik: zostaje self-hosted).
- **`README.md`** — tabela „Roles & Permissions" przepisana pod 6 ról, link do RBAC.md.

### Migration guide

1. `cd backend && alembic upgrade head` — migracja 0011 przemapuje istniejących userów (admin→admin, manager→delivery_lead, recruiter+sourcer/tac/DL→odpowiednio, recruiter+QC→user, client→user).
2. Restart backendu — guardy aktywne natychmiast.
3. Deploy frontendu — middleware aktywne od pierwszego requesta (cookie ustawia się przy następnym loginie).
4. **Istniejące tokeny pozostają ważne** — guardy backendu czytają rolę z DB (przez `get_current_user`), nie z JWT claim, więc migracja danych automatycznie przepina uprawnienia. Frontend middleware czyta claim z cookie, więc do momentu następnego loginu rola w UI może być stała — zaleca się wymusić logout wszystkim poprzez `UPDATE users SET is_active=false; ...; UPDATE users SET is_active=true;` LUB akceptacja, że użytkownicy zobaczą poprawne UI po następnym loginie (max 8h).

## [0.9.0] — 2026-04-16 — Phase 6: UI polish & coverage

Finishes every remaining item from the original roadmap. Pure UI/docs/tests — no schema
changes. All Phase 1-5 backend endpoints now have a matching UI.

### Added — UI

- **AddCandidateModal / EditCandidateModal** — new "Dane strukturalne" section (`years_it_experience`, `champion`, `verifier_id`, `verified_tech`) and "Preferencje kontraktowe" section (`remote_modes` chips, `rate_min/max`, `industries`, `contract_types` chips, `excluded_clients` multi-select). Writes through to `Candidate.preferences` JSONB.
- **AddJobModal / EditJobModal** — "Szablon procesu rekrutacyjnego" dropdown now lets users assign a `pipeline_template_id` at create/edit time. Defaults to "— domyślny szablon —".
- **SuggestedCandidatesWidget** — new job-detail widget exposing `/api/jobs/{id}/recommendations?include_breakdown=true`. Score chip 0-100, color-coded bands (75+/50+/25+/low), "dlaczego?" tooltip with per-layer bars + must/nice skill matches/gaps, "Przypisz" button that creates the CandidateStage on the default "new" stage. Top-3 results auto-logged to `/api/match-history`.
- **ScorecardModal** — opens after a successful kanban move to a stage with a non-empty `scorecard_schema.questions[]`. Renders rating/text/checkbox/select questions + overall rating + notes; submits via `PATCH /api/pipeline/{stage_id}/scorecard`.
- **SavedSearchPicker** — dropdown in Kandydaci list for saving/applying named filter presets. Shared vs private, inline delete. Applies `q/status/sort` filters atomically.
- **MatchHistoryWidget** — expandable per-job panel inside a candidate's "Rekrutacje" tab. Timeline of score snapshots with ScoreBreakdownTooltip.

### Added — Backend

- **JobCreate/JobUpdate** schemas — `pipeline_template_id` now accepted on create/update (previously only via `/assign-to-job`).
- **StageDefResponse** — exposes `scorecard_schema` so the frontend can detect which stages have defined questions.
- **Unit tests** — 36 pure-function tests in `tests/test_scoring_service.py` (22) and `tests/test_dedup_service.py` (14). Exercise `_skill_names`, `_score_skills`, `_score_salary`, `_score_location`, `_score_availability`, `score_semantic`, and every normalizer in `dedup_service`. All pass, zero external dependencies.

### Docs

- **README.md** — Features & Roadmap sections rewritten around Phases 1-5, API endpoints table expanded.
- **docs/pipeline-templates.md** — new how-to covering the template/StageDef/RejectionReason model, scorecard schema format, backward-compat guarantees, and the Traffit migration path.

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
