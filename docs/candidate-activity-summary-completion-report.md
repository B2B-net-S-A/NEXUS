# Podsumowanie aktywności kandydata (AI) — raport ukończenia

Data: 2026-07-29 · PR: #1003 · Branch: `claude/candidate-activity-summary-2f12cf`

## Zakres

Karta **„Podsumowanie aktywności"** na profilu kandydata (prawa szyna „Podsumowanie
AI", zakładka Podsumowanie) + przycisk **„Aktualizuj notatkę"**. AI kondensuje pełną
historię kandydata do krótkiej notatki PL (~150 słów): wysyłki na projekty (stanowisko,
klient, data, czy było interview + feedback), preferencje/ograniczenia, wcześniejsza
współpraca z klientami, stawki (ustalona + przedział z wysyłek), dostępność, okres
wypowiedzenia, powody odrzuceń, technologie.

## Pliki

**Backend**
- `backend/app/models/candidate_activity_summary.py` — tabela `candidate_activity_summaries`
  (1 wiersz/kandydata, UNIQUE, `input_hash`, `generated_by/at`).
- `backend/app/services/candidate_activity_summary_service.py` — zbieranie historii
  (stages+Job+Client, interview_feedback, screening_notes, notes ×30, contracts,
  candidate_rate_history, calls z summary), deterministyczne sekcje tekstowe →
  `input_hash` (sha256 + wersja promptu + model), gate kwot, wywołanie Claude
  (thinking disabled), sanityzacja, upsert z guardem IntegrityError.
- `backend/app/api/candidate_activity_summary.py` — `GET /api/candidates/{id}/activity-summary`
  (cache-only, darmowy) + `POST .../activity-summary/refresh` (10/min); oba `OperationalUser`.
- `backend/app/services/llm_prompts.py` — `CANDIDATE_ACTIVITY_SUMMARY` v1 (plaintext,
  zakaz fabrykacji, priorytety treści, pomijanie braków) + rejestr.
- `backend/app/models/ai_feature.py` — `FEATURE_DATA_SENT[candidate_summary]` urealnione.
- `backend/app/main.py`, `backend/app/models/__init__.py` — montaż/rejestracja.

**Migracje**
- `backend/alembic/versions/0204_candidate_activity_summaries.py` (head po 0203) —
  CREATE TABLE/INDEX IF NOT EXISTS + seed `ai_features('candidate_summary')` pod
  WHERE NOT EXISTS. Enum `aifeaturekey` ma wartość od 0085 — bez zmiany enuma.
- `backend/entrypoint.sh` — lustro DDL w `_COLUMN_STATEMENTS` + seed w
  `_DATA_STATEMENTS` (precedens cortex_skill_facts, incydent 2026-07-12).

**Frontend**
- `frontend/src/components/v2/pages/CandidateActivitySummaryCard.tsx` — karta w szynie
  AI: cache render (ExpandableText ×6 linii), empty state „Wygeneruj podsumowanie",
  „Aktualizuj notatkę" (spinner, toast „zaktualizowane" vs „aktualne — brak nowych
  danych"), provenance (model + data), błąd z retry.
- `frontend/src/lib/api.ts` — `activitySummaryApi` + typ `CandidateActivitySummary`.
- `frontend/src/components/v2/pages/candidate-query-keys.ts` — klucz `activitySummary`.
- `frontend/src/components/v2/pages/CandidateDetailV2.tsx` — montaż karty w aside.

## Decyzje projektowe

- **GET nigdy nie generuje** — karta siedzi na domyślnej zakładce profilu; przy 49k
  kandydatów auto-generacja na każdym otwarciu byłaby kosztowa. Pierwsza generacja
  wyłącznie przyciskiem.
- **Refresh płaci tylko przy zmianie historii** — `input_hash` (jak w match
  justification #156); bez zmian → `refreshed=false` i toast informacyjny.
- **Kwoty**: zarezerwowany `AIFeatureKey.candidate_summary` (istniał od 0085 jako
  nieużywany slot) — master kill-switch, per-feature toggle, miesięczny limit, licznik.
- **RBAC**: `OperationalUser` na obu endpointach (spójnie ze scoringiem — M3-SEC-01);
  kontrakt authz tras: nowe trasy klasyfikowane jako gated, baseline bez zmian.
- Wyjście plaintext (nie JSON) — mniej trybów awarii parsowania; nadal thinking
  disabled (trap truncacji na Sonnet 5, #632/#633).

## Weryfikacja

- BE: `29 passed` (14 nowych + suite match-justification) w obrazie py3.12;
  ruff check + format zielone; `app.openapi()` OK (823 trasy, brak trapu PEP 563);
  `alembic heads` = pojedyncza głowa `0204`; `tests/test_route_authz_contract.py` 14/14.
- FE: 5/5 Vitest (`CandidateActivitySummaryCard.test.tsx`), `tsc --noEmit` zielone,
  ESLint bez błędów na dotkniętych plikach.
- UI smoke przez Chrome na prod: do wykonania po deployu (endpoint dormant do
  pierwszego kliknięcia — brak migracji danych, zero ryzyka regresji przy starcie).

## Znane ograniczenia / TODO

- Wymaga `ANTHROPIC_API_KEY` w env (jest na prod dla CV generatora); model override:
  `CANDIDATE_SUMMARY_MODEL` (default `claude-sonnet-5`).
- Notatka nie odświeża się sama — tylko przycisk (świadome: koszt). Ewentualny
  auto-refresh po zmianie etapu = osobna decyzja produktowa.
- Feedback thumbs up/down (jak w scoringu) — nie wdrożony; łatwy follow-up.
