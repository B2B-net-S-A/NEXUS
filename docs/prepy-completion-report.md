# Feature "Prepy" — Completion Report

**Status:** ✅ Deployed to production (https://nexus.dynaminds.pl), smoke-tested.
**Commit:** `8a1742f feat(ai-cc): AI Competence Category matching + auto-collaborators + pool suggestions` on `origin/main`
**Backend tests:** 19/19 passing
**Data:** 2026-04-22

## Cel

Zbudować centralną, tagowalną bazę pytań rekrutacyjnych z fallbackiem do **podobnych projektów** (po CC + embedding), z zachowaniem **tenant isolation** (pytania klient-specific nie wyciekają do prep-kitów innych klientów).

## Co zostało zrobione

### 1. Modele danych (SQLAlchemy)

- **`interview_questions`** — centralna baza, tagowalna (CC, skills, seniority, type), ze wskazaniem `client_id` dla tenant isolation + partial unique indexes `uq_iq_client_hash` (per klient) i `uq_iq_global_hash` (bank globalny).
- **`job_questions`** — m2m pin między pytaniem a jobem, `order_index: Float` (fractional indexing pod drag-drop bez kolizji), `added_by_source` enum (`manual`/`auto_from_similar`/`auto_generated`).
- **`interview_question_ratings`** — audit trail thumb up/down. **Faza 1**: ratingi bez wpływu na ranking, żeby uniknąć feedback-loop bias.

Pliki: [backend/app/models/interview_question.py](backend/app/models/interview_question.py), [backend/alembic/versions/0042_interview_questions.py](backend/alembic/versions/0042_interview_questions.py).

### 2. Waterfall "suggest questions for prep" (6 warstw)

W serwisie [backend/app/services/question_suggestions.py](backend/app/services/question_suggestions.py):

1. **Pinned** — `JobQuestion` przypięte do tego joba (po `order_index`)
2. **Legacy champion** — `Job.champion_profile.screening_questions` (read-only — nowe wpisy idą już do `job_questions`)
3. **Tier 1** — jobs z tym samym primary `competence_category_id`, cosine `>= 0.70`
4. **Tier 2** — jobs overlapping po secondary CC (`JobSecondaryCc`), cosine `>= 0.55`, hard cap top-10
5. **Tier 3** — `ClientKnowledge.interview_questions` (legacy per-klient)
6. **Tier 4** — auto-generate z `job.must_skills` + `requirements` (bezpiecznik — zawsze coś zwraca)

Deduplication po `lowercase + collapse whitespace` — zachowuje priorytet wg warstwy.

### 3. Tenant isolation (KRYTYCZNE)

Hard rule w `_questions_for_jobs`:
```
WHERE question.client_id IS NULL
   OR question.client_id = <prep_kit_job.client_id>
```
Pytania `client_id != NULL` **nigdy** nie wyciekają do prep-kitów innych klientów. Testowane w `test_tenant_isolation_client_specific_question_not_leaked_cross_client`.

### 4. API endpointy — [backend/app/api/interview_questions.py](backend/app/api/interview_questions.py)

| Metoda | Path |
|---|---|
| POST | `/api/interview-questions` (auto-pin przez `job_id`) |
| GET | `/api/interview-questions` (filtry: `cc_id`, `skill_tag`, `seniority`, `question_type`, `client_id`, `q`) |
| GET/PUT/DELETE | `/api/interview-questions/{id}` |
| POST | `/api/jobs/{job_id}/questions/pin` |
| DELETE | `/api/jobs/{job_id}/questions/{question_id}` (unpin) |
| PATCH | `/api/jobs/{job_id}/questions/reorder` |
| GET | `/api/jobs/{job_id}/questions` (lista pinned) |
| POST | `/api/interview-questions/{id}/rate` |
| GET | `/api/jobs/{job_id}/suggested-questions?candidate_id=` — pełny waterfall z metadata (`source_tier`, `cosine_score`, `source_job_id`) |

Dedup przy create po `normalized_text_hash` — drugi POST z tą samą treścią zwraca istniejące pytanie.

### 5. Integracja z `prep_kit.py`

[backend/app/api/prep_kit.py](backend/app/api/prep_kit.py) — dotychczasowy endpoint `POST /api/prep-kit/generate` nadal zwraca `likely_questions: list[str]` (backwards-compat), dodano **nowe pole** `likely_questions_meta: list[dict]` z tierem i metadanymi. Implementacja teraz woła `suggest_questions_for_prep` pod maską.

### 6. Frontend (Next.js 15)

- **Dedykowana strona Prep** — [frontend/src/app/jobs/[id]/prep/[candidateId]/page.tsx](frontend/src/app/jobs/[id]/prep/[candidateId]/page.tsx) — drukowalna, z badge'ami tier (`pinned` / `z podobnego projektu` / `auto-gen`), kciuki up/down, CTA "Przypnij".
- **Komponent `QuestionCard`** — [frontend/src/components/prep/QuestionCard.tsx](frontend/src/components/prep/QuestionCard.tsx) — z obsługą rate/pin per pytanie.
- **Tab "Baza pytań"** w widoku joba — [frontend/src/components/prep/QuestionBankTab.tsx](frontend/src/components/prep/QuestionBankTab.tsx) — CRUD, wyszukiwanie w globalnej bazie (z tenant-safe filtrem UI), reorder up/down.
- Rozszerzenie [frontend/src/lib/api.ts](frontend/src/lib/api.ts) o `interviewQuestionsApi` (pełen CRUD + pin/unpin/reorder/rate/suggested) i typowany `PrepKitResponse`.

### 7. Seed z `champion_profile`

Migracja 0042 w kodzie Pythona (bez zależności od `pgcrypto`) iteruje po `jobs.champion_profile.screening_questions` → każde pytanie dostaje wpis w `interview_questions` (`source=imported_from_champion`, `client_id=job.client_id`) + auto-pin do joba. Idempotentne przez partial unique index.

## Ryzyka i mitigacje

| Ryzyko | Mitygacja |
|---|---|
| Cross-tenant question leak | Hard filter `client_id IS NULL OR = self.client_id`, testowane |
| Job bez embedding_id / CC | Graceful skip tier 1-2, fallback do tier 3-4 |
| Qdrant offline | try/except wokół search, waterfall leci do tier 3-4 |
| Dwuźródłowość champion_profile vs job_questions | Nowe wpisy idą wyłącznie do `job_questions`; `champion_profile` read-only |
| Rating feedback bias | Faza 1: ratingi audit-only, bez wpływu na ranking (waterfall deterministyczny) |

## Weryfikacja

### Backend — 19/19 testów passing

```bash
docker compose exec backend pytest tests/test_interview_questions.py -v
```

Pokrycie:
- Pure-function: hashing, bullet-list parse, legacy champion parse, auto-gen per skill
- API: create + dedup, pin/unpin, reorder z fractional indexing, rate audit trail
- Suggested endpoint — tier 4 gdy brak danych
- Prep-kit backwards-compat — `likely_questions: list[str]` nadal działa
- **Tenant isolation** — pytanie klienta A nie leci do joba klienta B mimo cosine 0.9

### Produkcja — Chrome MCP smoke test

1. ✅ Deploy zakończony — `/health` HTTP 200
2. ✅ `/api/interview-questions` HTTP 403 bez tokenu (endpoint zarejestrowany, auth działa)
3. ✅ `/jobs/[id]` renderuje tab "Baza pytań" (`data-testid="tab-questions"`)
4. ✅ Modal "Nowe pytanie" — wszystkie pola (text/ideal/type/seniority/tags/deal-breaker/zakres)
5. ✅ Utworzenie pytania + auto-pin do joba `#483` ("Jak zaimplementowałbyś idempotentny endpoint REST w FastAPI?") — widoczne w liście z badge "przypięte" i reorder-buttonami
6. ✅ Dedykowana strona `/jobs/999/prep/999` renderuje (error state dla nieistniejącego joba — jak zaprojektowano)

## Znane ograniczenia / scope out of phase 1

- **Semantic merge duplicate questions** (worker) — zostawione na fazę 2
- **Embeddingi per-pytanie** (osobna Qdrant collection) — faza 2 gdy bank urośnie
- **Rating-aware scoring w rankingu** (epsilon-greedy exploration) — faza 2
- **PDF export prep-kita** — opcjonalnie w przyszłości

## Kalibracja thresholdów

Thresholdy `TIER_1_MIN_COSINE=0.70` i `TIER_2_MIN_COSINE=0.55` to startowe wartości. Przez 2 tygodnie loguj faktyczne cosine w `question_suggestions.py` przez WARN-level, potem skaliibrowaj per CC.

## Gdzie jest kod

- Commit: `8a1742f`
- Migracja: `backend/alembic/versions/0042_interview_questions.py`
- Modele: `backend/app/models/interview_question.py`
- Serwis: `backend/app/services/question_suggestions.py`
- API: `backend/app/api/interview_questions.py`
- Modyfikacje: `backend/app/api/prep_kit.py`, `backend/app/services/embedding_service.py` (dodana `search_similar_jobs_by_job_id`)
- Testy: `backend/tests/test_interview_questions.py`
- Frontend: `frontend/src/app/jobs/[id]/prep/[candidateId]/page.tsx`, `frontend/src/components/prep/*`
- Plan: `/Users/arturtwardowski/.claude/plans/zrob-wedlug-twoich-rekomendacji-mighty-moore.md`
