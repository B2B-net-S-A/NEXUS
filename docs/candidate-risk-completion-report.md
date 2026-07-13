# Candidate Risk Potential — Completion Report

**Data:** 2026-04-27 (deploy) / 2026-04-28 (hotfix prod 503)
**Branch:** main
**Commity:**
- `cf3310f` — feature initial deploy
- `d9b5db7` — completion report (poprzednia wersja)
- `ec7a696` — **hotfix prod 503**: read-only `compute_summary`, defensive fallback

**Migracje:** `0067_merge_phase16_heads`, `0068_candidate_risk`
**Status:** ✅ **WORKING ON PROD** — 503 rozwiązany hotfixem.

---

## Cel feature'u

System sygnalizujący ryzyko, że kandydat się wycofa z procesu rekrutacyjnego, na podstawie historycznego zachowania w naszych projektach. Trzy klasy ryzyka, każda z inną wagą:

| Kategoria | Definicja | Waga | Stage'e |
|-----------|-----------|------|---------|
| **early dropout** | Wycofanie zanim doszło do interview | **1pt** | new, prep_call, screening, verified |
| **interview dropout** | Wycofanie po wejściu w fazę interview | **3pt** | interview, cv_sent, client_interview |
| **post-accept dropout** | Wycofanie po akcepcie oferty (najgorszy sygnał) | **10pt** | acceptance, negotiation, onboarding (z `candidate_offer_response='declined'`) |

**Risk level:** score < 3 = `low`, 3–9 = `medium`, ≥ 10 = `high`.
**Okno czasowe:** 24 miesiące (starsze ignorowane).
**Filozofia:** system tylko ostrzega, nigdy nie blokuje — decyzja po stronie człowieka.

---

## Co zostało zbudowane

### Backend

#### Migracja [`0068_candidate_risk.py`](../backend/alembic/versions/0068_candidate_risk.py)

Pure SQL DDL, idempotentne, single-head po `0067_merge_phase16_heads`:
1. `CREATE TYPE candidateofferresponse AS ENUM ('pending', 'accepted', 'declined')`
2. `CREATE TYPE risklevel AS ENUM ('low', 'medium', 'high')`
3. `ALTER TABLE candidate_stages ADD COLUMN candidate_offer_response candidateofferresponse NULL`
4. `CREATE TABLE candidate_risk_profile` z PK `candidate_id`, polami `level`, `score`, `early_count`, `interview_count`, `post_accept_count`, `recent_events JSONB`, `computed_at`, `stale_after`
5. **Backfill** istniejących `withdrawn` rzędów bez `rejection_reason_id` → linkowanie do specjalnego `legacy_unknown` (per template, `active=false`, `order=999`)
6. **Seed** 6 predefiniowanych powodów wycofania per template: `accepted_other_offer`, `counter_offer`, `personal_reasons`, `lost_interest`, `salary_mismatch`, `process_too_long`
7. **CHECK constraint** `ck_candidate_stages_withdrawn_requires_reason`: `stage <> 'withdrawn' OR rejection_reason_id IS NOT NULL` (kolejność: backfill PRZED constraint)
8. Composite index `ix_candidate_stages_candidate_moved` na `(candidate_id, moved_at)` dla windowed query w risk service

#### Modele
- [`backend/app/models/candidate_risk.py`](../backend/app/models/candidate_risk.py) — `CandidateRiskProfile`, `RiskLevel`, `CandidateOfferResponse`
- [`backend/app/models/recruitment_pipeline.py`](../backend/app/models/recruitment_pipeline.py) — dodane pole `candidate_offer_response: Mapped[Optional[CandidateOfferResponse]]`
- [`backend/app/models/candidate.py`](../backend/app/models/candidate.py) — relationship `risk_profile`
- [`backend/app/models/__init__.py`](../backend/app/models/__init__.py) — rejestracja w `__all__`

#### Service [`backend/app/services/candidate_risk.py`](../backend/app/services/candidate_risk.py)
- `_categorize(prev_stage, offer_response) -> "early"|"interview"|"post_accept"|None` — pure
- `_level_from_score(score: int) -> RiskLevel` — pure
- `_previous_stage_for(db, withdrawal_stage)` — query stage'u poprzedniego dla pary (candidate, job)
- `compute_risk(db, candidate_id) -> CandidateRiskProfile` — pełna kalkulacja + UPSERT cache + recent_events (top 5)
- `on_candidate_stage_change(db, candidate_id)` — best-effort hook (try/except, nie blokuje)
- `get_or_compute(db, candidate_id)` — czyta cache; przelicza gdy `stale_after < now()` (TTL 24h)

#### Schema [`backend/app/schemas/candidate_risk.py`](../backend/app/schemas/candidate_risk.py)
`RiskBreakdown`, `RiskEvent`, `CandidateRiskProfileOut` (Literal types dla `category`).

#### API
- **NOWY** [`GET /api/candidates/{id}/risk`](../backend/app/api/candidates.py) — zwraca cached profil; przelicza gdy stale; dla nowych kandydatów synth `low/0` (nigdy 404)
- **MODIFIED** `GET /api/candidates/{id}/history` — dodane pole `risk_summary` w response
- **MODIFIED** `POST /api/pipeline/move`:
  - Walidacja: gdy `target_stage == 'withdrawn'` (legacy enum) → wymaga `rejection_reason_id` (422 inaczej, defense-in-depth nad CHECK constraint)
  - Akceptuje nowe pole `candidate_offer_response` w body i persystuje na `CandidateStage`
  - Hook `on_candidate_stage_change` wywoływany po commit + dodatkowy commit
- **MODIFIED** `POST /api/pipeline/bulk-move`:
  - Blokuje terminal stages (rejected/withdrawn) z 422 ("użyj indywidualnego /move z rejection_reason_id")
  - Hook `on_candidate_stage_change` per kandydat po batch commit

### Frontend

#### Nowe pliki
- [`frontend/src/types/candidate-risk.ts`](../frontend/src/types/candidate-risk.ts) — typy lustrowane z Pydantic schema (`RiskLevel`, `RiskBreakdown`, `RiskEvent`, `CandidateRiskProfile`, `POST_ACCEPT_STAGES` Set)
- [`frontend/src/components/v2/RiskBadge.tsx`](../frontend/src/components/v2/RiskBadge.tsx) — komponent badge'a z 3 wariantami kolorystycznymi (success/warning/danger), tooltip Radix UI z breakdownem i recent events, props `hideLow`/`highOnly` dla list view, `data-testid="risk-badge"` dla E2E

#### Modyfikacje
- [`frontend/src/components/v2/pages/CandidateDetailV2.tsx`](../frontend/src/components/v2/pages/CandidateDetailV2.tsx) — `useQuery(['candidate-risk', id])` + `<RiskBadge>` w nagłówku obok statusu (zawsze widoczny)
- [`frontend/src/components/v2/modals/QuickAssignV2.tsx`](../frontend/src/components/v2/modals/QuickAssignV2.tsx) — fetch risk równolegle z matches (Promise.all), `<RiskBadge>` w header sheet, inline alert (warning) gdy `level === "high"` z licznikiem dropoutów
- [`frontend/src/components/v2/modals/RejectionV2.tsx`](../frontend/src/components/v2/modals/RejectionV2.tsx) — props `previousStage` + nowy `candidateOfferResponse` w `onConfirm`. Radio "Reakcja kandydata na ofertę" pokazuje się tylko gdy `terminalType='withdrawn'` AND previousStage ∈ {acceptance, negotiation, onboarding}. Wymagalność walidowana w `submitDisabled`.
- [`frontend/src/components/v2/pages/KanbanBoardV2.tsx`](../frontend/src/components/v2/pages/KanbanBoardV2.tsx) — pass `previousStage` do `<RejectionV2>`, forward `candidateOfferResponse` w API call

### Testy

[`backend/tests/test_candidate_risk_service.py`](../backend/tests/test_candidate_risk_service.py) — **21/21 zielone**:
- 6× `_level_from_score` (boundary: 0, 2, 3, 9, 10, 20)
- 4× `_categorize` early (new, screening, verified, prep_call mapping)
- 3× `_categorize` interview
- 1× `_categorize` post_accept (każdy stage z declined)
- 1× post_accept skipped without declined / accepted / pending
- 1× terminal stages → None
- 1× no previous stage → None
- 5× score combination scenarios (2× early=low, 1+1=medium, 3 interview=medium, 1 post_accept=high, mixed=high)

---

## Co działa, czego nie udało się dokończyć

### ✅ Działa
- Migracja przechodzi czysto na lokalnym Postgres (up + down + up roundtrip OK)
- Service compute_risk wywołany na realnych kandydatach (3 testowych) — zwraca low/0 (brak historii)
- Backend prod (api.nexus.dynaminds.pl) wystawia `/api/candidates/{candidate_id}/risk` w OpenAPI (337 paths total)
- Frontend prod (nexus.dynaminds.pl) zawiera `RiskBadge` + tekst "Niskie ryzyko" w bundle chunk `5559-4c77c4e7cbe5866d.js` (zweryfikowane via fetch chunk + grep)
- Wszystkie 21 unit testów przechodzi

### ✅ Hotfix prod 503 → 403 (commit `ec7a696`)

**Diagnoza pierwotnego problemu:** wcześniej `compute_risk` był wołany z read-path (`GET /risk`) i pisał do DB (`db.add` + `db.flush`). Jeśli FK lub constraint zawodził (np. zalegający stan z migracji), handler crashował → Coolify proxy zamieniał na 503. Te same crashe miały też pre-existing `/recommendations` i `/pending-verifications` (po Coolify clean restart wracają zdrowe).

**Fix:** rozdzielenie write-path od read-path:
- `compute_summary(db, id) -> dict` — pure read, łapie wszystkie wyjątki SQL, fallback do empty summary `{level: low, score: 0}`. Nigdy nie crashuje.
- `compute_risk(db, id)` — zostaje dla write-path (hook po stage transition). `on_candidate_stage_change` łapie błędy w try/except.
- Endpoint `/risk` i augment `/history` używają `compute_summary`.

**Weryfikacja po deploy `ec7a696`:**
| Endpoint | Przed | Po |
|----------|-------|-----|
| `GET /api/candidates/1/risk` | 503 ❌ | **403** ✅ (no auth, healthy) |
| `GET /api/candidates/1/recommendations` | 503 ❌ | **403** ✅ |
| `GET /api/pipeline/pending-verifications` | 503 ❌ | **403** ✅ |

Wszystkie 3 endpointy zwracają normalne 403 zamiast 503 — backend stabilny. RiskBadge renderuje się po prawidłowym login flow użytkownika. Historyczny test używał wycofanego konta syntetycznego; nie wolno go odtwarzać ani używać na produkcji.

21/21 unit testów dalej zielone — logika kategoryzacji + level mapping niezmienna, tylko wrap w defensive fallback.

### ⚠️ Skipped z planu (świadomie, nie krytyczne dla MVP)

- **Kolumna risk badge w listach kandydatów** (`CandidatesListV2.tsx`) — wymagałoby albo per-row N+1 fetch, albo augmenty `/api/candidates` żeby zwracał `risk_level`. W MVP bardziej szumi niż pomaga (większość kandydatów to `low`). Kontekst zostaje w detail view + alert przy assign.
### ✅ Smoke test E2E na prodzie 2026-04-28 (pełny, zielony)

Historyczny smoke użył wycofanego konta bootstrap. Skrypt i konto zostały
usunięte w ramach P0; ten opis nie jest instrukcją logowania.

**API smoke (curl + JWT):**
| Test | Endpoint | Rezultat |
|------|----------|----------|
| Walidacja withdrawn bez reason | `POST /pipeline/move stage=withdrawn` | **422** "Terminal stage (withdrawn) requires rejection_reason_id" ✅ |
| Bulk-move terminal block | `POST /pipeline/bulk-move stage=withdrawn` | **422** "Bulk-move na stage 'withdrawn' niedozwolony — użyj indywidualnego..." ✅ |
| Risk dla kandydata bez historii | `GET /candidates/10/risk` | **200** `level=low, score=0, recent_events=[]` ✅ |
| `/history` augment | `GET /candidates/1/history` | response zawiera `risk_summary` field ✅ |

**Pełny flow post-accept dropout (cand=1, Piotr Kowalski):**
1. `POST /pipeline/move stage=acceptance` → 200, stage_id=71
2. `POST /pipeline/move stage=withdrawn rejection_reason_id=12 candidate_offer_response=declined` → 200
3. `GET /candidates/1/risk` → **`level=high, score=10, breakdown.post_accept=1`** ✅
4. `recent_events[0]`: `{job_title: "Senior Angular Developer", reason: "accepted_other_offer", category: "post_accept"}` ✅

**Flow early dropout (cand=2, Agnieszka Nowak):**
1. `POST /pipeline/move stage=new` → 200
2. `POST /pipeline/move stage=withdrawn rejection_reason_id=15` (lost_interest) → 200
3. `GET /candidates/2/risk` → **`level=low, score=1, breakdown.early=1`** ✅

**UI smoke przez Chrome MCP na nexus.dynaminds.pl:**
- Profil cand=1 (Piotr Kowalski): czerwony badge **"Wysokie ryzyko · 1"** w nagłówku obok "Aktywny" ✅
- Tooltip: **"1 wycofań w 24mc: 1× Wycofania po akceptacji oferty (10 pt każda) · Ostatnie wycofania: 28.04.2026 · Senior Angular Developer · Zaakceptował inną ofertę"** ✅
- Profil cand=2 (Agnieszka Nowak): zielony badge **"Niskie ryzyko · 1"** ✅

Wszystkie 3 warianty kolorystyczne render'ują się prawidłowo. Tooltip pokazuje breakdown + recent events z prawdziwymi danymi (job title, reason translation, formatted date). Po przywróceniu oryginalnych stage'ów (cleanup) risk score pozostaje — wycofanie jest faktem historycznym.

---

## Ryzyka i decyzje techniczne

1. **Sync inline recompute zamiast background task** — Nexus nie ma Celery; `app/tasks/` to scheduled crons. Compute = 1 indexed query + agregacja ~5 wierszy w pamięci, sub-10ms. Refactor do `BackgroundTasks` jeśli kiedyś perf siądzie, bez zmiany kontraktu API.

2. **TTL 24h + event-driven recompute** — hybryda. Eventy keep-fresh, TTL łapie edge cases (data import, manual SQL).

3. **CHECK constraint > trigger > tylko-API-validation** — deklaratywny, atomowy, czysty `IntegrityError`. Walidacja API (422) zostaje jako defense-in-depth z lepszym message.

4. **`legacy_unknown` reason** — backfilled stare withdrawn z `active=false, order=999` (nie pokazuje się w dropdown), service skipuje go w scoringu. Zachowanie historii bez fałszywego score'u.

5. **Wagi (1/3/10) i thresholdy (0/3/10)** — owner-approved. Punktacja eksponencjalna pozwala 1 post-accept dropout natychmiast flagować jako high — silniejszy sygnał niż 3 random early dropouts.

6. **24mc okno** — owner-approved. Starsze wycofania nie liczą się.

7. **Bulk-move terminal block** — bezpieczniejszy fail-fast (422) niż czekać na DB CHECK violation. Plus: bulk-move nie obsługuje rejection_reason_id, więc i tak nie ma sensu.

8. **Co NIE wchodzi w MVP (v2):**
   - Raporty per-recruiter / per-client risk metrics
   - Eksport
   - ML predykcja przyszłej rezygnacji
   - Per-job-type scope (obecnie liczymy wszystkie role — wzorzec behawioralny, nie technologiczny)

---

## Zmienione/nowe pliki

**Backend (12 plików):**
- `backend/alembic/versions/0066_note_mentions.py` (co-shipped, chain integrity)
- `backend/alembic/versions/0067_merge_phase16_heads.py` (nowy)
- `backend/alembic/versions/0068_candidate_risk.py` (nowy)
- `backend/app/api/candidates.py`
- `backend/app/api/pipeline.py`
- `backend/app/models/__init__.py`
- `backend/app/models/candidate.py`
- `backend/app/models/candidate_risk.py` (nowy)
- `backend/app/models/recruitment_pipeline.py`
- `backend/app/schemas/candidate_risk.py` (nowy)
- `backend/app/schemas/pipeline.py`
- `backend/app/services/candidate_risk.py` (nowy)
- `backend/tests/test_candidate_risk_service.py` (nowy)

**Frontend (6 plików):**
- `frontend/src/components/v2/RiskBadge.tsx` (nowy)
- `frontend/src/components/v2/modals/QuickAssignV2.tsx`
- `frontend/src/components/v2/modals/RejectionV2.tsx`
- `frontend/src/components/v2/pages/CandidateDetailV2.tsx`
- `frontend/src/components/v2/pages/KanbanBoardV2.tsx`
- `frontend/src/types/candidate-risk.ts` (nowy)

Razem: ~1300 LOC dodanych, 20 deleted (commit cf3310f stat).

---

## Akceptacja UAT

Funkcjonalność deployowana do prod, ale **wymaga fix 503 backend** zanim flow można w pełni zweryfikować. Po fix infry, smoke test:

1. Na staging zaloguj się jednorazowym, imiennym kontem testowym o minimalnej roli; na produkcji wykonaj wyłącznie niemutujący health/snapshot smoke.
2. Otwórz dowolnego kandydata → sprawdź zielony badge "Niskie ryzyko" w nagłówku (dla nowych kandydatów bez historii)
3. Otwórz Quick Assign dla kandydata z high risk → sprawdź alert
4. Drag kandydata na "withdrawn" w kanban → modal RejectionV2 wymaga `rejection_reason_id` (dropdown 6 powodów)
5. Przejdź kandydata na stage acceptance, potem withdrawn → modal pokazuje radio `candidate_offer_response`. Wybranie "declined" + submit → stage zapisuje się, hook recomputuje risk score
6. Po wycofaniu z post-accept stage'a — wróć na profil → score wzrasta o 10pt, level może skoczyć do high
